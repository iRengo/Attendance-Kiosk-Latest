from fastapi import APIRouter
from fastapi.responses import JSONResponse
import threading
import time
import json

from . import state

router = APIRouter()


def _ensure_outbox_table(conn):
    conn.execute(
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


def process_outbox_once():
    # lazy import to reuse firestore client from sync.py
    try:
        from . import sync
    except Exception:
        sync = None

    db_fs = getattr(sync, "db_fs", None) if sync is not None else None

    conn = state.get_db()
    _ensure_outbox_table(conn)
    cur = conn.cursor()

    # select using rowid as id to be resilient to schema differences
    cur.execute(
        "SELECT rowid as id, local_session_id, queued_at, status, attempts FROM attendance_sessions_outbox WHERE status = ? OR (status = ? AND attempts < ?) ORDER BY rowid ASC",
        ("queued", "failed", 5),
    )
    rows = cur.fetchall()
    results = []

    for outbox in rows:
        outbox_id, local_session_id, queued_at, status, attempts = outbox
        try:
            # load session metadata
            s_cur = conn.cursor()
            s_cur.execute(
                "SELECT class_id, teacher_id, date, roomId, timeEnded FROM attendance_sessions WHERE id = ?",
                (local_session_id,)
            )
            srow = s_cur.fetchone()

            if not srow:
                # nothing to push; mark failed
                cur.execute(
                    "UPDATE attendance_sessions_outbox SET status = ?, attempts = ? WHERE rowid = ?",
                    ("failed", (attempts or 0) + 1, outbox_id),
                )
                conn.commit()
                results.append({"outbox_id": outbox_id, "status": "no_session_row"})
                continue

            class_id, teacher_id, date_field, roomId, timeEnded = srow

            # fetch attendance entries for this session
            s_cur.execute(
                "SELECT student_id, timeLogged, status FROM attendance_entries WHERE session_id = ?",
                (local_session_id,)
            )
            entries = s_cur.fetchall()

            if not db_fs:
                # Firestore not configured; mark as failed for retries
                cur.execute(
                    "UPDATE attendance_sessions_outbox SET status = ?, attempts = ? WHERE rowid = ?",
                    ("failed", (attempts or 0) + 1, outbox_id),
                )
                conn.commit()
                results.append({"outbox_id": outbox_id, "status": "no_firestore_client"})
                continue

            # write per-student docs under /students/{studentId}/attendance/{sessionId}
            batch = db_fs.batch()
            batch_count = 0

            def commit_batch(b):
                b.commit()

            session_doc_id = str(local_session_id)
            time_logged_default = timeEnded or time.strftime("%Y-%m-%dT%H:%M:%S%z")

            for student_id, timeLogged, status_val in entries:
                doc_ref = db_fs.collection("students").document(str(student_id)).collection("attendance").document(session_doc_id)
                doc = {
                    "classId": class_id,
                    "teacherId": teacher_id,
                    "roomId": roomId,
                    "date": date_field,
                    "timeLogged": timeLogged if timeLogged else None,
                    "status": status_val,
                }
                batch.set(doc_ref, doc)
                batch_count += 1
                # commit periodically to respect batch size limits
                if batch_count >= 400:
                    commit_batch(batch)
                    batch = db_fs.batch()
                    batch_count = 0

            if batch_count > 0:
                commit_batch(batch)

            # attempt to also write the full session document under _attendance_sessions
            try:
                session_doc = {
                    "classId": class_id,
                    "teacherId": teacher_id,
                    "date": date_field,
                    "roomId": roomId,
                    "timeEnded": timeEnded,
                    "timeLoggedDefault": time_logged_default,
                    "entries": [],
                }
                for student_id, timeLogged, status_val in entries:
                    session_doc["entries"].append({"student_id": student_id, "timeLogged": timeLogged, "status": status_val})

                try:
                    dbfs_collection = db_fs.collection("_attendance_sessions")
                    dbfs_collection.document(session_doc_id).set(session_doc)
                except Exception:
                    # don't fail entire outbox on this; continue to mark per-student docs
                    pass
            except Exception:
                pass

            # mark outbox as synced
            cur.execute(
                "UPDATE attendance_sessions_outbox SET status = ?, attempts = ? WHERE rowid = ?",
                ("synced", (attempts or 0) + 1, outbox_id),
            )
            conn.commit()
            results.append({"outbox_id": outbox_id, "status": "synced", "session_doc_id": session_doc_id})

        except Exception as e:
            attempts_new = (attempts or 0) + 1
            status_new = "queued" if attempts_new < 5 else "failed"
            try:
                cur.execute(
                    "UPDATE attendance_sessions_outbox SET status = ?, attempts = ? WHERE rowid = ?",
                    (status_new, attempts_new, outbox_id),
                )
                conn.commit()
            except Exception:
                pass
            results.append({"outbox_id": outbox_id, "status": "error", "error": str(e)})

    conn.close()
    return results


def _loop_worker():
    while True:
        try:
            process_outbox_once()
        except Exception:
            pass
        time.sleep(10)


try:
    t = threading.Thread(target=_loop_worker, daemon=True)
    t.start()
except Exception:
    pass


@router.get("/sync/outbox/status")
def outbox_status():
    try:
        conn = state.get_db()
        _ensure_outbox_table(conn)
        cur = conn.cursor()
        # use rowid as id for compatibility
        cur.execute(
            "SELECT rowid as id, local_session_id, queued_at, status, attempts FROM attendance_sessions_outbox ORDER BY rowid DESC LIMIT 50"
        )
        rows = cur.fetchall()
        conn.close()
        items = []
        for r in rows:
            items.append({"id": r[0], "local_session_id": r[1], "queued_at": r[2], "status": r[3], "attempts": r[4]})
        # add a brief summary counts for UI
        try:
            conn2 = state.get_db()
            cur2 = conn2.cursor()
            cur2.execute("SELECT COUNT(*) FROM attendance_sessions_outbox")
            total = cur2.fetchone()[0]
            cur2.execute("SELECT COUNT(*) FROM attendance_sessions_outbox WHERE status = ?", ("queued",))
            queued = cur2.fetchone()[0]
            cur2.execute("SELECT COUNT(*) FROM attendance_sessions_outbox WHERE status = ?", ("failed",))
            failed = cur2.fetchone()[0]
            cur2.execute("SELECT COUNT(*) FROM attendance_sessions_outbox WHERE status = ?", ("synced",))
            synced = cur2.fetchone()[0]
            conn2.close()
        except Exception:
            total = queued = failed = synced = 0

        summary = {
            "total": total,
            "queued": queued,
            "failed": failed,
            "synced": synced,
        }

        # If nothing to show, include a friendly message
        message = None
        if total == 0:
            message = "no_outbox_records"
        elif queued == 0 and failed == 0 and synced == 0:
            message = "no_pending_or_synced_records"

        return {"outbox": items, "summary": summary, "message": message}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/sync/outbox/process")
@router.get("/sync/outbox/process")
def trigger_outbox_process():
    try:
        res = process_outbox_once()
        return {"processed": res}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
from fastapi import APIRouter
from fastapi.responses import JSONResponse
import threading
import time
import json

from . import state

router = APIRouter()


def _ensure_outbox_table(conn):
    conn.execute(
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


def process_outbox_once():
    # lazy import to reuse firestore client from sync.py
    try:
        from . import sync
    except Exception:
        sync = None

    db_fs = getattr(sync, "db_fs", None) if sync is not None else None

    conn = state.get_db()
    _ensure_outbox_table(conn)
    cur = conn.cursor()

    # select using rowid as id to be resilient to schema differences
    cur.execute(
        "SELECT rowid as id, local_session_id, queued_at, status, attempts FROM attendance_sessions_outbox WHERE status = ? OR (status = ? AND attempts < ?) ORDER BY rowid ASC",
        ("queued", "failed", 5),
    )
    rows = cur.fetchall()
    results = []
    for outbox in rows:
        outbox_id, local_session_id, queued_at, status, attempts = outbox
        try:
            # load session metadata
            s_cur = conn.cursor()
            s_cur.execute(
                "SELECT class_id, teacher_id, date, roomId, timeEnded FROM attendance_sessions WHERE id = ?",
                (local_session_id,)
            )
            srow = s_cur.fetchone()
            if not srow:
                # nothing to push; mark failed
                cur.execute(
                    "UPDATE attendance_sessions_outbox SET status = ?, attempts = ? WHERE rowid = ?",
                    ("failed", (attempts or 0) + 1, outbox_id),
                )
                conn.commit()
                results.append({"outbox_id": outbox_id, "status": "no_session_row"})
                continue

            class_id, teacher_id, date_field, roomId, timeEnded = srow

            # fetch attendance entries for this session
            s_cur.execute(
                "SELECT student_id, timeLogged, status FROM attendance_entries WHERE session_id = ?",
                (local_session_id,)
            )
            entries = s_cur.fetchall()

            if not db_fs:
                cur.execute(
                    "UPDATE attendance_sessions_outbox SET status = ?, attempts = ? WHERE rowid = ?",
                    ("failed", (attempts or 0) + 1, outbox_id),
                )
                conn.commit()
                results.append({"outbox_id": outbox_id, "status": "no_firestore_client"})
                continue

            # write per-student docs under /students/{studentId}/attendance/{sessionId}
            batch = db_fs.batch()
            batch_count = 0
            def commit_batch(b):
                b.commit()

            session_doc_id = str(local_session_id)
            time_logged_default = timeEnded or time.strftime("%Y-%m-%dT%H:%M:%S%z")

            for student_id, timeLogged, status_val in entries:
                doc_ref = db_fs.collection("students").document(str(student_id)).collection("attendance").document(session_doc_id)
                doc = {
                    "classId": class_id,
                    "teacherId": teacher_id,
                    "roomId": roomId,
                    "date": date_field,
                    "timeLogged": timeLogged if timeLogged else None,
                    "status": status_val,
                }
                # if no timeLogged and absent, keep as null to signal absent
                batch.set(doc_ref, doc)
                batch_count += 1
                if batch_count >= 400:
                    commit_batch(batch)
                    batch = db_fs.batch()
                    batch_count = 0

            if batch_count > 0:
                commit_batch(batch)

            # mark outbox as synced
            cur.execute("UPDATE attendance_sessions_outbox SET status = ?, attempts = ? WHERE rowid = ?", ("synced", (attempts or 0) + 1, outbox_id))
            conn.commit()
            results.append({"outbox_id": outbox_id, "status": "synced", "session_doc_id": session_doc_id})

        except Exception as e:
            attempts_new = (attempts or 0) + 1
            status_new = "queued" if attempts_new < 5 else "failed"
            try:
                cur.execute(
                    "UPDATE attendance_sessions_outbox SET status = ?, attempts = ? WHERE rowid = ?",
                    (status_new, attempts_new, outbox_id),
                )
                conn.commit()
            except Exception:
                pass
            results.append({"outbox_id": outbox_id, "status": "error", "error": str(e)})

    conn.close()
    return results


def _loop_worker():
    while True:
        try:
            process_outbox_once()
        except Exception:
            pass
        time.sleep(10)


try:
    t = threading.Thread(target=_loop_worker, daemon=True)
    t.start()
except Exception:
    pass


@router.get("/sync/outbox/status")
def outbox_status():
    try:
        conn = state.get_db()
        _ensure_outbox_table(conn)
        cur = conn.cursor()
        # use rowid as id for compatibility
        cur.execute(
            "SELECT rowid as id, local_session_id, queued_at, status, attempts FROM attendance_sessions_outbox ORDER BY rowid DESC LIMIT 50"
        )
        rows = cur.fetchall()
        conn.close()
        items = []
        for r in rows:
            items.append({"id": r[0], "local_session_id": r[1], "queued_at": r[2], "status": r[3], "attempts": r[4]})
        return {"outbox": items}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.post("/sync/outbox/process")
@router.get("/sync/outbox/process")
def trigger_outbox_process():
    try:
        res = process_outbox_once()
        return {"processed": res}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
