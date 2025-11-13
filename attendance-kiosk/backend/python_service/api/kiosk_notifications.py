from fastapi import APIRouter
from fastapi.responses import JSONResponse
import time
import os
import json

from . import state
from . import sync as _sync
import sqlite3

router = APIRouter()


def insert_local_and_maybe_remote(props: dict):
    """Insert a local kiosk notification into sqlite.

    This is best-effort: it will insert the row locally and return.
    If a notif with the same `notif_id` already exists, the insert is ignored.
    """
    try:
        conn = state.get_db()
        cur = conn.cursor()
        notif_id = props.get('notif_id') or f"notif-{int(time.time())}"
        kiosk_id = props.get('kiosk_id')
        room = props.get('room')
        # If kiosk_id or room not provided, attempt to read from local kiosks_fs table
        try:
            if (not kiosk_id or not room):
                try:
                    cur.execute("SELECT fs_id, assignedRoomId FROM kiosks_fs LIMIT 1")
                    r = cur.fetchone()
                    if r:
                        if not kiosk_id:
                            kiosk_id = r[0]
                        if not room:
                            room = r[1]
                except Exception:
                    pass
        except Exception:
            pass
        title = props.get('title') or props.get('msg') or ''
        ntype = props.get('type') or 'info'
        details = props.get('details')
        # store details as JSON string for flexibility
        details_s = None
        try:
            details_s = json.dumps(details) if details is not None else None
        except Exception:
            try:
                details_s = str(details)
            except Exception:
                details_s = None

        timestamp = props.get('timestamp') or time.strftime("%Y-%m-%dT%H:%M:%S%z")
        createdAt = props.get('createdAt') or timestamp

        # Use INSERT OR IGNORE to avoid duplicate notif_id entries
        cur.execute(
            "INSERT OR IGNORE INTO kiosk_notifications (notif_id,kiosk_id,room,title,type,details,timestamp,createdAt) VALUES (?,?,?,?,?,?,?,?)",
            (notif_id, kiosk_id, room, title, ntype, details_s, timestamp, createdAt),
        )
        conn.commit()
        try:
            conn.close()
        except Exception:
            pass
        # After inserting locally, attempt to push all pending notifications to Firestore
        try:
            if getattr(_sync, 'db_fs', None):
                _push_pending_to_firestore(_sync.db_fs)
        except Exception:
            pass
        return True
    except Exception:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        return False


def _push_pending_to_firestore(db_fs):
    """Push local pending kiosk_notifications rows to Firestore.

    Uses notif_id as the Firestore document id (if available) to avoid duplicates.
    Updates local row with fs_id and sync_status='synced' on success.
    """
    if not db_fs:
        return
    conn = None
    try:
        conn = state.get_db()
        cur = conn.cursor()
        # select rows that haven't been synced (sync_status != 'synced' or fs_id is null)
        cur.execute("SELECT id, notif_id, kiosk_id, room, title, type, details, timestamp, createdAt FROM kiosk_notifications WHERE sync_status != 'synced' OR fs_id IS NULL")
        rows = cur.fetchall()
        for r in rows:
            local_id = r[0]
            notif_id = r[1] or f"notif-{int(time.time())}-{local_id}"
            kiosk_id = r[2]
            room = r[3]
            title = r[4]
            ntype = r[5]
            details_s = r[6]
            timestamp = r[7]
            createdAt = r[8]
            # parse details JSON if present
            details = None
            try:
                if details_s:
                    import json as _json
                    details = _json.loads(details_s)
            except Exception:
                details = details_s

            # Build Firestore doc data
            doc = {
                'notif_id': notif_id,
                'kiosk_id': kiosk_id,
                'room': room,
                'title': title,
                'type': ntype,
                'details': details,
                'timestamp': timestamp,
                'createdAt': createdAt,
            }
            try:
                # Use notif_id as document id to make this idempotent
                db_fs.collection('kiosk_notifications').document(str(notif_id)).set(doc)
                # mark local row as synced
                try:
                    cur.execute("UPDATE kiosk_notifications SET fs_id = ?, sync_status = 'synced' WHERE id = ?", (str(notif_id), local_id))
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
            except Exception:
                # leave as pending
                continue
    except Exception:
        pass
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


@router.get("/kiosk_notifications")
def list_notifications(limit: int = 100):
    """Return recent kiosk notifications (most recent first)."""
    try:
        conn = state.get_db()
        cur = conn.cursor()
        cur.execute("SELECT notif_id,kiosk_id,room,title,type,details,timestamp,createdAt,fs_id FROM kiosk_notifications ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        res = []
        for r in rows:
            details = r[5]
            try:
                details = json.loads(details) if details else None
            except Exception:
                pass
            res.append({
                'notif_id': r[0],
                'kiosk_id': r[1],
                'room': r[2],
                'title': r[3],
                'type': r[4],
                'details': details,
                'timestamp': r[6],
                'createdAt': r[7],
                'fs_id': r[8],
            })
        try:
            conn.close()
        except Exception:
            pass
        return res
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
