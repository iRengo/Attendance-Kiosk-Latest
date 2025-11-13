from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import json
import time
from datetime import datetime, timezone
import os

from . import state

# optional import for recognition and firestore push
try:
    from . import recognition
except Exception:
    recognition = None
try:
    from . import sync
except Exception:
    sync = None

router = APIRouter()


def _read_rpi_serial():
    try:
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.strip().startswith("Serial"):
                        parts = line.split(":")
                        if len(parts) >= 2:
                            return parts[1].strip()
    except Exception:
        pass
    return None


def _ensure_attendance_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id TEXT,
            teacher_id TEXT,
            date TEXT,
            isActive TEXT,
            roomId TEXT,
            studentsPresent TEXT,
            studentsAbsent TEXT,
            timeStarted TEXT,
            timeEnded TEXT,
            raw_doc JSON
        )
    """
    )
    # per-session per-student attendance entries
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            student_id TEXT,
            timeLogged TEXT,
            status TEXT,
            created_at TEXT,
            UNIQUE(session_id, student_id)
        )
    """
    )
    # session history table: store summary records for ended sessions
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kiosk_fs_id TEXT,
            room_fs_id TEXT,
            class_id TEXT,
            class_name TEXT,
            students_present_total INTEGER,
            timeStarted TEXT,
            timeEnded TEXT,
            teacher_id TEXT,
            date TEXT,
            raw_doc JSON,
            createdAt TEXT
        )
    """
    )


@router.get("/session")
def get_session():
    return {"session": state.current_session}


@router.get("/session/classes")
def get_classes_for_teacher(teacher_id: str):
    """Return classes for a given teacher id from the local sqlite DB."""
    try:
        conn = state.get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name, subjectName, gradeLevel, section FROM classes WHERE teacher_id = ?", (teacher_id,))
        rows = cur.fetchall()
        # determine today's date prefix (ISO date)
        try:
            today_prefix = time.strftime("%Y-%m-%d")
        except Exception:
            today_prefix = None

        # gather class ids that already have an attendance_sessions row started today for this teacher
        started_today = set()
        try:
            if today_prefix:
                # attendance_sessions rows started today
                try:
                    cur.execute(
                        "SELECT DISTINCT class_id FROM attendance_sessions WHERE teacher_id = ? AND date LIKE ?",
                        (teacher_id, f"{today_prefix}%"),
                    )
                    srows = cur.fetchall()
                except Exception:
                    srows = []

                if srows:
                    for sr in srows:
                        try:
                            if sr and sr[0] is not None:
                                started_today.add(str(sr[0]))
                        except Exception:
                            pass

                # also gather class ids that already have a session recorded today from session_history
                try:
                    cur.execute(
                        "SELECT DISTINCT class_id FROM session_history WHERE teacher_id = ? AND createdAt LIKE ?",
                        (teacher_id, f"{today_prefix}%"),
                    )
                    srows2 = cur.fetchall()
                except Exception:
                    srows2 = []

                if srows2:
                    for sr in srows2:
                        try:
                            if sr and sr[0] is not None:
                                started_today.add(str(sr[0]))
                        except Exception:
                            pass
        except Exception:
            # ignore failures; started_today may remain empty
            pass

        conn.close()
        classes = []
        for r in rows:
            cid = r[0]
            classes.append({
                "id": cid,
                "name": r[1],
                "subjectName": r[2],
                "gradeLevel": r[3],
                "section": r[4],
                "disabledToday": str(cid) in started_today,
            })
        return {"classes": classes}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/session/start")
async def start_session(request: Request):
    """Start a session for a teacher/class. Body: {teacher_id, teacher_name, class_id, class_name}

    Persists a row in attendance_sessions (local DB) and updates state.current_session.
    """
    try:
        body = await request.json()
        teacher_id = body.get("teacher_id")
        teacher_name = body.get("teacher_name")
        class_id = body.get("class_id")
        class_name = body.get("class_name")

        state.current_session["teacher_id"] = teacher_id
        state.current_session["teacher_name"] = teacher_name
        state.current_session["class_id"] = class_id
        state.current_session["class_name"] = class_name

        # persist to local DB
        conn = state.get_db()
        _ensure_attendance_table(conn)
        # determine kiosk fs id and assigned room (best-effort)
        kiosk_fs_id = None
        room_fs_id = None
        try:
            serial_local = _read_rpi_serial()
            if serial_local:
                try:
                    cur_loc = conn.cursor()
                    cur_loc.execute("SELECT fs_id, assignedRoomId FROM kiosks_fs WHERE serialNumber = ?", (serial_local,))
                    kro = cur_loc.fetchone()
                    if kro:
                        kiosk_fs_id = kro[0]
                        room_fs_id = kro[1]
                except Exception:
                    pass
            if not kiosk_fs_id:
                try:
                    cur_loc = conn.cursor()
                    cur_loc.execute("SELECT fs_id, assignedRoomId FROM kiosks_fs LIMIT 1")
                    kro = cur_loc.fetchone()
                    if kro:
                        kiosk_fs_id = kro[0]
                        room_fs_id = kro[1]
                except Exception:
                    pass
        except Exception:
            pass
        # use timezone-aware ISO format for timestamps
        try:
            now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        conn.execute(
            "INSERT INTO attendance_sessions (class_id, teacher_id, date, isActive, roomId, studentsPresent, studentsAbsent, timeStarted, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (class_id, teacher_id, now, "true", room_fs_id, json.dumps([]), json.dumps([]), now, json.dumps(body)),
        )
        conn.commit()
        # mirror the session to Firestore immediately (best-effort)
        try:
            db_fs = getattr(sync, "db_fs", None) if sync is not None else None
            # build a deterministic doc id similar to stop_session logic
            doc_id = None
            if db_fs:
                try:
                    def _sanitize(s: str) -> str:
                        if not s:
                            return ""
                        return "".join(c for c in s.replace(" ", "_") if (c.isalnum() or c in "-__")).strip("_")

                    class_part = None
                    try:
                        conn2 = state.get_db()
                        cur2 = conn2.cursor()
                        cur2.execute("SELECT subjectName, gradeLevel, section, name FROM classes WHERE id = ?", (class_id,))
                        rclass = cur2.fetchone()
                        if rclass:
                            subject, grade, section, cname = rclass[0], rclass[1], rclass[2], rclass[3]
                            parts = []
                            if subject:
                                parts.append(str(subject))
                            if section:
                                parts.append(str(section))
                            if grade:
                                parts.append(str(grade))
                            class_part = "_".join(parts) if parts else (cname or None)
                        try:
                            conn2.close()
                        except Exception:
                            pass
                    except Exception:
                        try:
                            if conn2:
                                conn2.close()
                        except Exception:
                            pass

                    date_part = str(now).split("T")[0]
                    if class_part:
                        class_part = _sanitize(class_part)[:120]
                    else:
                        class_part = _sanitize(class_name)[:120] if class_name else "unknown_class"
                    doc_id = f"{class_part}_{date_part}"

                    session_doc = {
                        "classId": class_id,
                        "teacherId": teacher_id,
                        "date": now,
                        "isActive": True,
                        "roomId": room_fs_id,
                        "studentsPresent": [],
                        "studentsAbsent": [],
                        "timeStarted": now,
                        "timeEnded": None,
                        "entries": [],
                        "raw_doc": body,
                    }
                    try:
                        db_fs.collection("attendance_sessions").document(doc_id).set(session_doc)
                    except Exception:
                        pass

                    # mirror to local attendance_sessions_fs table as well
                    try:
                        loc_conn = state.get_db()
                        loc_cur = loc_conn.cursor()
                        loc_cur.execute(
                            """
                            CREATE TABLE IF NOT EXISTS attendance_sessions_fs (
                                fs_id TEXT PRIMARY KEY,
                                class_id TEXT,
                                teacher_id TEXT,
                                date TEXT,
                                isActive TEXT,
                                roomId TEXT,
                                studentsPresent JSON,
                                studentsAbsent JSON,
                                timeStarted TEXT,
                                timeEnded TEXT,
                                raw_doc JSON
                            )
                        """
                        )
                        try:
                            loc_cur.execute(
                                "INSERT OR REPLACE INTO attendance_sessions_fs (fs_id, class_id, teacher_id, date, isActive, roomId, studentsPresent, studentsAbsent, timeStarted, timeEnded, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    doc_id,
                                    class_id,
                                    teacher_id,
                                    now,
                                    str(True),
                                    room_fs_id,
                                    json.dumps([]),
                                    json.dumps([]),
                                    now,
                                    None,
                                    json.dumps(body),
                                ),
                            )
                            loc_conn.commit()
                        except Exception:
                            try:
                                loc_conn.rollback()
                            except Exception:
                                pass
                        try:
                            loc_conn.close()
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    doc_id = None
        except Exception:
            pass

        conn.close()

        return {"status": "started", "session": state.current_session}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/session/stop")
def stop_session():
    try:
        # require teacher re-authentication via camera recognition before stopping
        tid = state.current_session.get("teacher_id")
        cid = state.current_session.get("class_id")
        if not tid or not cid:
            return JSONResponse(content={"error": "no_active_session"}, status_code=400)

        # Check recognition result: teacher must be recognized and match the active teacher
        try:
            latest = None
            if recognition is not None:
                latest = getattr(recognition, "latest_teacher_result", None)
            if not latest or latest.get("status") != "success" or str(latest.get("id")) != str(tid):
                return JSONResponse(content={"error": "teacher_reauthentication_required", "reason": "teacher_not_recognized"}, status_code=403)
        except Exception:
            return JSONResponse(content={"error": "teacher_reauthentication_required", "reason": "recognition_unavailable"}, status_code=503)

        conn = state.get_db()
        _ensure_attendance_table(conn)
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        # fetch the most recent active session row for this teacher+class
        cur = conn.cursor()
        cur.execute(
            "SELECT id, class_id, teacher_id, date, isActive, roomId, studentsPresent, studentsAbsent, timeStarted, timeEnded, raw_doc FROM attendance_sessions WHERE teacher_id = ? AND class_id = ? AND isActive = ? ORDER BY id DESC LIMIT 1",
            (tid, cid, "true"),
        )
        row = cur.fetchone()

        if not row:
            conn.close()
            return {"status": "stopped", "warning": "no_active_row_found"}

        # Map columns according to SELECT above
        row_id = row[0]
        # class_id = row[1]
        # teacher_id = row[2]
        session_date = row[3]
        # isActive = row[4]
        row_roomId = row[5]
        studentsPresent_json = row[6]
        studentsAbsent_json = row[7]
        timeStarted = row[8]
        # timeEnded = row[9]
        raw_doc = row[10]
        try:
            present = json.loads(studentsPresent_json) if studentsPresent_json else []
        except Exception:
            present = []

        # compute absentees from class_students
        try:
            cur.execute("SELECT student_id FROM class_students WHERE class_id = ?", (cid,))
            enrolled_rows = cur.fetchall()
            enrolled = [r[0] for r in enrolled_rows] if enrolled_rows else []
        except Exception:
            enrolled = []

        absent = [s for s in enrolled if s not in present]

        # update attendance_sessions row: set studentsAbsent, isActive=false, timeEnded
        cur.execute(
            "UPDATE attendance_sessions SET studentsAbsent = ?, isActive = ?, timeEnded = ? WHERE id = ?",
            (json.dumps(absent), "false", now, row_id),
        )
        conn.commit()

        # insert attendance_entries for absent students (no timeLogged)
        try:
            for sid in absent:
                try:
                    cur.execute(
                        "INSERT OR REPLACE INTO attendance_entries (session_id, student_id, timeLogged, status, created_at) VALUES (?, ?, ?, ?, ?)",
                        (row_id, sid, None, "absent", now),
                    )
                except Exception:
                    pass
            conn.commit()
        except Exception:
            pass

        # enqueue outbox row to push per-student attendance to Firestore (non-blocking)
        try:
            # create a minimal compatible outbox table if it doesn't exist
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_sessions_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    local_session_id INTEGER,
                    queued_at TEXT,
                    status TEXT,
                    attempts INTEGER DEFAULT 0
                )
            """
            )

            # Check actual columns to support older/alternate schemas
            cols = [c[1] for c in cur.execute("PRAGMA table_info(attendance_sessions_outbox)").fetchall()]

            if "local_session_id" in cols:
                # preferred schema: store local_session_id
                cur.execute(
                    "INSERT INTO attendance_sessions_outbox (local_session_id, queued_at, status, attempts) VALUES (?, ?, ?, ?)",
                    (row_id, now, "queued", 0),
                )
            else:
                # fallback: store minimal info into the existing schema (map fields if available)
                # try common alternative columns: local_id/class_id/teacher_id/created_at
                if "created_at" in cols and "class_id" in cols and "teacher_id" in cols:
                    raw = json.dumps({"local_session_id": row_id})
                    cur.execute(
                        "INSERT INTO attendance_sessions_outbox (class_id, teacher_id, created_at, status, attempts, raw_doc) VALUES (?, ?, ?, ?, ?, ?)",
                        (cid, tid, now, "queued", 0, raw),
                    )
                else:
                    # last resort: attempt a very small insert into status/created_at if available
                    if "created_at" in cols and "status" in cols:
                        cur.execute(
                            "INSERT INTO attendance_sessions_outbox (created_at, status, attempts) VALUES (?, ?, ?)",
                            (now, "queued", 0),
                        )
                    else:
                        # If schema is unexpected, create a simple compatible table alongside and insert there
                        cur.execute(
                            "CREATE TABLE IF NOT EXISTS attendance_sessions_outbox_v2 (id INTEGER PRIMARY KEY AUTOINCREMENT, local_session_id INTEGER, queued_at TEXT, status TEXT, attempts INTEGER DEFAULT 0)"
                        )
                        cur.execute(
                            "INSERT INTO attendance_sessions_outbox_v2 (local_session_id, queued_at, status, attempts) VALUES (?, ?, ?, ?)",
                            (row_id, now, "queued", 0),
                        )
            conn.commit()
        except Exception as e:
            print(f"Warning: failed to enqueue attendance outbox: {e}")

        # Persist a session_history summary row locally
        try:
            # ensure table exists
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kiosk_fs_id TEXT,
                    room_fs_id TEXT,
                    class_id TEXT,
                    class_name TEXT,
                    students_present_total INTEGER,
                    timeStarted TEXT,
                    timeEnded TEXT,
                    teacher_id TEXT,
                    date TEXT,
                    raw_doc JSON,
                    createdAt TEXT
                )
            """
            )

            # determine kiosk fs id and assigned room (best-effort)
            kiosk_fs_id = None
            room_fs_id = None
            try:
                serial_local = _read_rpi_serial()
                if serial_local:
                    try:
                        cur.execute("SELECT fs_id, assignedRoomId FROM kiosks_fs WHERE serialNumber = ?", (serial_local,))
                        kro = cur.fetchone()
                        if kro:
                            kiosk_fs_id = kro[0]
                            room_fs_id = kro[1]
                    except Exception:
                        pass
                if not kiosk_fs_id:
                    try:
                        cur.execute("SELECT fs_id, assignedRoomId FROM kiosks_fs LIMIT 1")
                        kro = cur.fetchone()
                        if kro:
                            kiosk_fs_id = kro[0]
                            room_fs_id = kro[1]
                    except Exception:
                        pass
            except Exception:
                pass

            # determine class name if possible
            class_name = state.current_session.get("class_name") or None
            if not class_name:
                try:
                    cur.execute("SELECT name FROM classes WHERE id = ?", (cid,))
                    cr = cur.fetchone()
                    if cr:
                        class_name = cr[0]
                except Exception:
                    pass

            # fetch the session date if present
            session_date = None
            try:
                cur.execute("SELECT date FROM attendance_sessions WHERE id = ?", (row_id,))
                dr = cur.fetchone()
                if dr:
                    session_date = dr[0]
            except Exception:
                session_date = None

            students_present_total = len(present) if present is not None else 0

            cur.execute(
                "INSERT INTO session_history (kiosk_fs_id, room_fs_id, class_id, class_name, students_present_total, timeStarted, timeEnded, teacher_id, date, raw_doc, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kiosk_fs_id, room_fs_id, cid, class_name, students_present_total, timeStarted, now, tid, session_date, raw_doc, now),
            )
            conn.commit()
            # attempt to push history to Firestore (best-effort)
            try:
                db_fs = getattr(sync, "db_fs", None) if sync is not None else None
                if db_fs:
                    doc = {
                        "kiosk_fs_id": kiosk_fs_id,
                        "room_fs_id": room_fs_id,
                        "class_name": class_name,
                        "students_present_total": students_present_total,
                        "timeStarted": timeStarted,
                        "timeEnded": now,
                        "teacher_id": tid,
                        "date": session_date,
                        "raw_doc": json.loads(raw_doc) if raw_doc else None,
                        "createdAt": now,
                    }
                    try:
                        # use Firestore auto-id to avoid collisions
                        db_fs.collection("session_history").add(doc)
                    except Exception:
                        # ignore failures
                        pass
            except Exception:
                pass
        except Exception as e:
            print(f"Warning: failed to persist session_history: {e}")

        conn.close()
        # attempt to push the full attendance session document to Firestore _attendance_sessions
        try:
            db_fs = getattr(sync, "db_fs", None) if sync is not None else None
            if db_fs:
                # gather entries
                conn2 = state.get_db()
                cur2 = conn2.cursor()
                cur2.execute("SELECT student_id, timeLogged, status, created_at FROM attendance_entries WHERE session_id = ?", (row_id,))
                entries_rows = cur2.fetchall()
                conn2.close()

                entries = []
                for r in entries_rows:
                    entries.append({"student_id": r[0], "timeLogged": r[1], "status": r[2], "created_at": r[3]})

                session_doc = {
                    "classId": cid,
                    "teacherId": tid,
                    "date": session_date if session_date is not None else now,
                    "isActive": False,
                    "roomId": row_roomId if row_roomId is not None else room_fs_id,
                    "studentsPresent": present,
                    "studentsAbsent": absent,
                    "timeStarted": timeStarted,
                    "timeEnded": now,
                    "entries": entries,
                    "raw_doc": json.loads(raw_doc) if raw_doc else None,
                }
                try:
                    # Build a deterministic Firestore document id using class name + date (date portion only).
                    # Prefer the in-memory state class_name/teacher_name; fall back to DB lookups if missing.
                    class_name = state.current_session.get("class_name") or None
                    teacher_name = state.current_session.get("teacher_name") or None
                    if not class_name or not teacher_name:
                        # attempt to read from local DB
                        try:
                            conn3 = state.get_db()
                            cur3 = conn3.cursor()
                            if not class_name:
                                cur3.execute("SELECT name FROM classes WHERE id = ?", (cid,))
                                r = cur3.fetchone()
                                if r:
                                    class_name = r[0]
                            if not teacher_name:
                                cur3.execute("SELECT firstname, lastname FROM teachers WHERE id = ?", (tid,))
                                r2 = cur3.fetchone()
                                if r2:
                                    teacher_name = (r2[0] or "") + (" " + (r2[1] or "") if r2[1] else "")
                            conn3.close()
                        except Exception:
                            try:
                                if conn3:
                                    conn3.close()
                            except Exception:
                                pass

                    # Build doc id from class metadata: subjectName, gradeLevel, section + date
                    def _sanitize(s: str) -> str:
                        if not s:
                            return ""
                        return "".join(c for c in s.replace(" ", "_") if (c.isalnum() or c in "-__")).strip("_")

                    # prefer class subject/grade/section for id to meet requirement
                    class_part = None
                    try:
                        conn3 = state.get_db()
                        cur3 = conn3.cursor()
                        cur3.execute("SELECT subjectName, gradeLevel, section, name FROM classes WHERE id = ?", (cid,))
                        rclass = cur3.fetchone()
                        if rclass:
                            subject, grade, section, cname = rclass[0], rclass[1], rclass[2], rclass[3]
                            parts = []
                            if subject:
                                parts.append(str(subject))
                            if section:
                                parts.append(str(section))
                            if grade:
                                parts.append(str(grade))
                            class_part = "_".join(parts) if parts else (cname or None)
                        conn3.close()
                    except Exception:
                        try:
                            if conn3:
                                conn3.close()
                        except Exception:
                            pass

                    date_str = session_doc.get("date") or now
                    date_part = str(date_str).split("T")[0]
                    if class_part:
                        class_part = _sanitize(class_part)[:120]
                    else:
                        class_part = _sanitize(class_name)[:120] if class_name else "unknown_class"
                    doc_id = f"{class_part}_{date_part}"

                    # Keep the actual room FS id in roomId and include a human-readable roomLabel
                    room_label = None
                    if teacher_name or class_name:
                        tn = teacher_name or ""
                        cn = class_name or ""
                        room_label = f"{tn} - {cn}".strip(" -")

                    session_doc_clean = {
                        "classId": session_doc.get("classId"),
                        "teacherId": session_doc.get("teacherId"),
                        "date": session_doc.get("date"),
                        "isActive": session_doc.get("isActive"),
                        # prefer the stored room id from the session row (row_roomId/room_fs_id)
                        "roomId": session_doc.get("roomId"),
                        # include a human-readable label for convenience
                        "roomLabel": room_label,
                        "studentsPresent": session_doc.get("studentsPresent"),
                        "studentsAbsent": session_doc.get("studentsAbsent"),
                        "timeStarted": session_doc.get("timeStarted"),
                        "timeEnded": session_doc.get("timeEnded"),
                        "entries": session_doc.get("entries", []),
                    }

                    try:
                        dbfs_collection = db_fs.collection("attendance_sessions")
                        dbfs_collection.document(doc_id).set(session_doc_clean)
                    except Exception as e:
                        # Firestore push failed; log and continue — outbox will attempt per-student push
                        print(f"Warning: failed to push attendance session to Firestore: {e}")
                    # Also persist the session document locally into attendance_sessions_fs so
                    # tools that read the local Firestore mirror table see the new session immediately
                    try:
                        loc_conn = state.get_db()
                        loc_cur = loc_conn.cursor()
                        loc_cur.execute(
                            """
                            CREATE TABLE IF NOT EXISTS attendance_sessions_fs (
                                fs_id TEXT PRIMARY KEY,
                                class_id TEXT,
                                teacher_id TEXT,
                                date TEXT,
                                isActive TEXT,
                                roomId TEXT,
                                studentsPresent JSON,
                                studentsAbsent JSON,
                                timeStarted TEXT,
                                timeEnded TEXT,
                                raw_doc JSON
                            )
                        """
                        )
                        try:
                            loc_cur.execute(
                                "INSERT OR REPLACE INTO attendance_sessions_fs (fs_id, class_id, teacher_id, date, isActive, roomId, studentsPresent, studentsAbsent, timeStarted, timeEnded, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    doc_id,
                                    session_doc_clean.get("classId"),
                                    session_doc_clean.get("teacherId"),
                                    session_doc_clean.get("date"),
                                    str(session_doc_clean.get("isActive")),
                                    session_doc_clean.get("roomId"),
                                    json.dumps(session_doc_clean.get("studentsPresent") or []),
                                    json.dumps(session_doc_clean.get("studentsAbsent") or []),
                                    session_doc_clean.get("timeStarted"),
                                    session_doc_clean.get("timeEnded"),
                                    json.dumps(session_doc_clean.get("raw_doc") or {}),
                                ),
                            )
                            loc_conn.commit()
                            try:
                                print(f"Mirrored session to local attendance_sessions_fs: {doc_id}")
                            except Exception:
                                pass
                        except Exception:
                            try:
                                loc_conn.rollback()
                            except Exception:
                                pass
                        try:
                            loc_conn.close()
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

        # finally clear the in-memory session state (only after successful re-auth and local updates)
        state.current_session["teacher_id"] = None
        state.current_session["teacher_name"] = None
        state.current_session["class_id"] = None
        state.current_session["class_name"] = None

        return {"status": "stopped"}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/session/mark")
async def mark_student_present(request: Request):
    """Mark a recognized student as present for the current active session.

    Body: { student_id: str, student_name: str }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    student_id = body.get("student_id")
    student_name = body.get("student_name")

    # ensure session active
    active_teacher = state.current_session.get("teacher_id")
    active_class = state.current_session.get("class_id")
    if not active_teacher or not active_class:
        return JSONResponse(content={"error": "no_active_session"}, status_code=400)

    if not student_id:
        return JSONResponse(content={"error": "missing_student_id"}, status_code=400)

    try:
        conn = state.get_db()
        _ensure_attendance_table(conn)
        cur = conn.cursor()
        # find the most recent active attendance_sessions row for this teacher+class
        cur.execute(
            "SELECT id, studentsPresent, studentsAbsent, timeStarted, roomId FROM attendance_sessions WHERE teacher_id = ? AND class_id = ? AND isActive = ? ORDER BY id DESC LIMIT 1",
            (active_teacher, active_class, "true"),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return JSONResponse(content={"error": "no_active_attendance_row"}, status_code=404)
        row_id, studentsPresent_json, studentsAbsent_json, timeStarted, row_roomId = row
        try:
            present = json.loads(studentsPresent_json) if studentsPresent_json else []
        except Exception:
            present = []
        # append if not already present
        if student_id not in present:
            # determine status based on timeStarted: present if within <1 minute, late if >=1 minute
            try:
                now_dt = datetime.now(timezone.utc)
                now_iso = now_dt.isoformat()
            except Exception:
                now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                try:
                    now_dt = datetime.strptime(now_iso, "%Y-%m-%dT%H:%M:%S%z")
                except Exception:
                    now_dt = datetime.now()

            status = "present"
            try:
                if timeStarted:
                    try:
                        start_dt = datetime.strptime(timeStarted, "%Y-%m-%dT%H:%M:%S%z")
                    except Exception:
                        # fallback: parse without timezone
                        try:
                            start_dt = datetime.strptime(timeStarted.split('+')[0], "%Y-%m-%dT%H:%M:%S")
                            start_dt = start_dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            start_dt = None
                    if start_dt is not None:
                        diff_minutes = (now_dt - start_dt).total_seconds() / 60.0
                        # present if less than 1 minute, late if >= 1 minute
                        if diff_minutes < 0.20:
                            status = "present"
                        elif diff_minutes >= 0.33:
                            status = "late"
            except Exception:
                status = "present"

            # update local session present list
            if status in ("present", "late"):
                present.append(student_id)
                try:
                    cur.execute("UPDATE attendance_sessions SET studentsPresent = ? WHERE id = ?", (json.dumps(present), row_id))
                    conn.commit()
                except Exception:
                    pass

            # record attendance entry with timeLogged and status
            try:
                time_logged_val = now_iso if status in ("present", "late") else None
                cur.execute(
                    "INSERT OR REPLACE INTO attendance_entries (session_id, student_id, timeLogged, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (row_id, student_id, time_logged_val, status, now_iso),
                )
                conn.commit()
            except Exception:
                pass

            # attempt to update Firestore: per-student doc and session doc (best-effort)
            try:
                db_fs = getattr(sync, "db_fs", None) if sync is not None else None
                if db_fs:
                    # build session doc id (same deterministic scheme as start/stop)
                    def _sanitize(s: str) -> str:
                        if not s:
                            return ""
                        return "".join(c for c in s.replace(" ", "_") if (c.isalnum() or c in "-__")).strip("_")

                    session_doc_id = None
                    try:
                        # prefer in-memory class_name if available
                        class_name = state.current_session.get("class_name") or None
                        conn3 = state.get_db()
                        cur3 = conn3.cursor()
                        cur3.execute("SELECT subjectName, gradeLevel, section, name FROM classes WHERE id = ?", (active_class,))
                        rclass = cur3.fetchone()
                        class_part = None
                        if rclass:
                            subject, grade, section, cname = rclass[0], rclass[1], rclass[2], rclass[3]
                            parts = []
                            if subject:
                                parts.append(str(subject))
                            if section:
                                parts.append(str(section))
                            if grade:
                                parts.append(str(grade))
                            class_part = "_".join(parts) if parts else (cname or None)
                        try:
                            conn3.close()
                        except Exception:
                            pass
                        date_part = str(now_iso).split("T")[0]
                        if class_part:
                            class_part = _sanitize(class_part)[:120]
                        else:
                            class_part = _sanitize(class_name)[:120] if class_name else str(active_class)
                        session_doc_id = f"{class_part}_{date_part}"
                    except Exception:
                        session_doc_id = None

                    # write per-student attendance under students/{id}/attendance/{session_doc_id}
                    try:
                        if session_doc_id:
                            student_doc = {
                                "classId": active_class,
                                "teacherId": active_teacher,
                                "roomId": row_roomId,
                                "date": now_iso,
                                "timeLogged": time_logged_val,
                                "status": status,
                            }
                            try:
                                db_fs.collection("students").document(str(student_id)).collection("attendance").document(session_doc_id).set(student_doc)
                            except Exception:
                                pass

                            # update session doc arrays (studentsPresent). Use full arrays to avoid duplicates.
                            try:
                                session_updates = {"studentsPresent": present}
                                db_fs.collection("attendance_sessions").document(session_doc_id).set(session_updates, merge=True)
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                pass
        conn.close()
        return {"status": "marked", "studentsPresent": present}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/session/attendance")
def get_current_attendance():
    """Return the studentsPresent/studentsAbsent arrays for the active session (if any)."""
    try:
        active_teacher = state.current_session.get("teacher_id")
        active_class = state.current_session.get("class_id")
        if not active_teacher or not active_class:
            return {"studentsPresent": [], "studentsAbsent": []}
        conn = state.get_db()
        _ensure_attendance_table(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT studentsPresent, studentsAbsent FROM attendance_sessions WHERE teacher_id = ? AND class_id = ? AND isActive = ? ORDER BY id DESC LIMIT 1",
            (active_teacher, active_class, "true"),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"studentsPresent": [], "studentsAbsent": []}
        studentsPresent_json, studentsAbsent_json = row
        try:
            present = json.loads(studentsPresent_json) if studentsPresent_json else []
        except Exception:
            present = []
        try:
            absent = json.loads(studentsAbsent_json) if studentsAbsent_json else []
        except Exception:
            absent = []
        return {"studentsPresent": present, "studentsAbsent": absent}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/session/attendance_entries")
def get_current_attendance_entries():
    """Return attendance_entries rows for the active session."""
    try:
        active_teacher = state.current_session.get("teacher_id")
        active_class = state.current_session.get("class_id")
        if not active_teacher or not active_class:
            return {"entries": []}
        conn = state.get_db()
        _ensure_attendance_table(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM attendance_sessions WHERE teacher_id = ? AND class_id = ? ORDER BY id DESC LIMIT 1",
            (active_teacher, active_class),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"entries": []}
        session_id = row[0]
        cur.execute(
            "SELECT student_id, timeLogged, status, created_at FROM attendance_entries WHERE session_id = ?",
            (session_id,)
        )
        rows = cur.fetchall()
        conn.close()
        items = []
        for r in rows:
            items.append({"student_id": r[0], "timeLogged": r[1], "status": r[2], "created_at": r[3]})
        return {"entries": items}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/session/history")
def get_session_history(limit: int = 50):
    """Return recent session_history rows from local DB."""
    try:
        conn = state.get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, kiosk_fs_id, room_fs_id, class_id, class_name, students_present_total, timeStarted, timeEnded, teacher_id, date, raw_doc, createdAt FROM session_history ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = cur.fetchall()
        conn.close()
        items = []
        for r in rows:
            # raw_doc may be stored as JSON string; attempt to parse
            raw_doc_val = None
            try:
                raw_doc_val = json.loads(r[10]) if r[10] else None
            except Exception:
                raw_doc_val = r[10]
            items.append({
                "id": r[0],
                "kiosk_fs_id": r[1],
                "room_fs_id": r[2],
                "class_id": r[3],
                "class_name": r[4],
                "students_present_total": r[5],
                "timeStarted": r[6],
                "timeEnded": r[7],
                "teacher_id": r[8],
                "date": r[9],
                "raw_doc": raw_doc_val,
                "createdAt": r[11],
            })
        return {"history": items}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
