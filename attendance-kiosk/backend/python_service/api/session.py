from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import json
import time
from datetime import datetime, timezone

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
        conn.close()
        classes = []
        for r in rows:
            classes.append({"id": r[0], "name": r[1], "subjectName": r[2], "gradeLevel": r[3], "section": r[4]})
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
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        conn.execute(
            "INSERT INTO attendance_sessions (class_id, teacher_id, date, isActive, roomId, studentsPresent, studentsAbsent, timeStarted, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (class_id, teacher_id, now, "true", None, json.dumps([]), json.dumps([]), now, json.dumps(body)),
        )
        conn.commit()
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
            "SELECT id, studentsPresent, studentsAbsent, timeStarted, raw_doc FROM attendance_sessions WHERE teacher_id = ? AND class_id = ? AND isActive = ? ORDER BY id DESC LIMIT 1",
            (tid, cid, "true"),
        )
        row = cur.fetchone()

        if not row:
            conn.close()
            return {"status": "stopped", "warning": "no_active_row_found"}

        row_id, studentsPresent_json, studentsAbsent_json, timeStarted, raw_doc = row
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
                    "date": row[3] if row[3] is not None else now,
                    "isActive": False,
                    "roomId": row[4] if len(row) > 4 else None,
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

                    # sanitize class name for doc id and extract date portion (YYYY-MM-DD)
                    def _sanitize(s: str) -> str:
                        if not s:
                            return ""
                        return "".join(c for c in s.replace(" ", "_") if (c.isalnum() or c in "-__")).strip("_")

                    date_str = session_doc.get("date") or now
                    # prefer just the date part (before 'T') for id
                    date_part = str(date_str).split("T")[0]
                    class_part = _sanitize(class_name)[:120] if class_name else "unknown_class"
                    doc_id = f"{class_part}_{date_part}"

                    # Replace roomId with teacher name + class name as requested, and remove raw_doc to avoid redundancy
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
                        "roomId": room_label,
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
            "SELECT id, studentsPresent, studentsAbsent, timeStarted FROM attendance_sessions WHERE teacher_id = ? AND class_id = ? AND isActive = ? ORDER BY id DESC LIMIT 1",
            (active_teacher, active_class, "true"),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return JSONResponse(content={"error": "no_active_attendance_row"}, status_code=404)
        row_id, studentsPresent_json, studentsAbsent_json, timeStarted = row
        try:
            present = json.loads(studentsPresent_json) if studentsPresent_json else []
        except Exception:
            present = []
        # append if not already present
        if student_id not in present:
            present.append(student_id)
            cur.execute("UPDATE attendance_sessions SET studentsPresent = ? WHERE id = ?", (json.dumps(present), row_id))
            conn.commit()

            # record attendance entry with timeLogged and status
            try:
                now_dt = datetime.now(timezone.utc)
                now_iso = now_dt.isoformat()
                status = "present"
                # compute minutes late relative to timeStarted
                try:
                    if timeStarted:
                        try:
                            start_dt = datetime.strptime(timeStarted, "%Y-%m-%dT%H:%M:%S%z")
                        except Exception:
                            # fallback: parse without timezone
                            start_dt = datetime.strptime(timeStarted.split('+')[0], "%Y-%m-%dT%H:%M:%S")
                            start_dt = start_dt.replace(tzinfo=timezone.utc)
                        diff_minutes = (now_dt - start_dt).total_seconds() / 60.0
                        if diff_minutes > 30:
                            status = "late"
                        else:
                            status = "present"
                except Exception:
                    status = "present"

                cur.execute(
                    "INSERT OR REPLACE INTO attendance_entries (session_id, student_id, timeLogged, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (row_id, student_id, now_iso, status, now_iso),
                )
                conn.commit()
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
