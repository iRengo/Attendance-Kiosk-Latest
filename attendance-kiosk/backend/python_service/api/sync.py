from fastapi import APIRouter
from fastapi.responses import JSONResponse
from . import state
import os
import json
import shutil
import requests
import time

try:
    import numpy as np
except Exception:
    np = None

try:
    import cv2
except Exception:
    cv2 = None

from . import recognition
from . import media
import io
try:
    from PIL import Image
except Exception:
    Image = None

router = APIRouter()

# Initialize Firestore client if credentials exist (optional)
db_fs = None
cred_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "serviceAccountKey.json"))
try:
    from firebase_admin import credentials, firestore, initialize_app
    if os.path.exists(cred_path):
        try:
            cred = credentials.Certificate(cred_path)
            initialize_app(cred)
            db_fs = firestore.client()
        except Exception:
            db_fs = None
    else:
        db_fs = None
except Exception:
    db_fs = None


@router.get("/sync")
def sync_firestore():
    if not db_fs:
        # Firestore client not configured. Return a clearer hint instead of a generic 500.
        return JSONResponse(
            content={
                "error": "service account not configured or firestore unavailable",
                "hint": f"Place your Firebase service account JSON at {cred_path} and restart the service, or use /sync/local_reload to refresh local embeddings from the DB.",
            },
            status_code=400,
        )
    conn = None
    try:
        DB_PATH = getattr(state, 'DB_PATH', None)
        if DB_PATH and os.path.exists(DB_PATH):
            try:
                shutil.copy(DB_PATH, DB_PATH + ".bak")
            except Exception as e:
                print(f"Warning: failed to backup DB: {e}")

        conn = state.get_db()
        cursor = conn.cursor()
        synced_count = {"students": 0, "teachers": 0, "classes": 0, "class_students": 0}

        teachers_ref = db_fs.collection("teachers").stream()
        for doc in teachers_ref:
            data = doc.to_dict()
            teacher_id = doc.id
            profile_url = data.get("profilePicUrl") or data.get("profile_pic_url")
            raw_json = json.dumps(data, default=str)
            emb = None
            if profile_url:
                try:
                    resp = requests.get(profile_url, timeout=15, allow_redirects=True)
                    if resp.status_code == 200:
                        content = resp.content
                        # Save a local copy of the profile image (best-effort)
                        try:
                            local_path = media.save_profile_photo(teacher_id, 'teachers', content)
                            if local_path:
                                profile_url = local_path
                        except Exception:
                            pass

                        img = None
                        # Try OpenCV decode first if available
                        if cv2 is not None and np is not None:
                            try:
                                img_array = np.asarray(bytearray(content), dtype=np.uint8)
                                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                            except Exception:
                                img = None
                        # Fallback to PIL if OpenCV not available or failed
                        if img is None and Image is not None:
                            try:
                                pil = Image.open(io.BytesIO(content)).convert('RGB')
                                img = np.asarray(pil)[:, :, ::-1] if np is not None else None
                            except Exception:
                                img = None

                        if img is not None:
                            try:
                                # ensure model is prepared
                                mdl = recognition._init_model() or recognition.model
                                if mdl is not None:
                                    small = cv2.resize(img, (320, 240)) if cv2 is not None else img
                                    try:
                                        faces = mdl.get(small)
                                    except Exception:
                                        faces = []
                                    if faces:
                                        emb = faces[0].embedding.tobytes()
                            except Exception as e:
                                print(f"Model processing failed for teacher {teacher_id}: {e}")
                except Exception as e:
                    print(f"Error downloading/processing teacher {teacher_id}: {e}")

            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO teachers (
                        id, firstname, middlename, lastname,
                        school_email, personal_email, status, temp_password,
                        profilePicUrl, createdAt, updatedAt, embedding, raw_doc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        teacher_id,
                        data.get("firstname"),
                        data.get("middlename"),
                        data.get("lastname"),
                        data.get("school_email"),
                        data.get("personal_email"),
                        data.get("status"),
                        data.get("temp_password"),
                        profile_url,
                        data.get("createdAt"),
                        data.get("updatedAt"),
                        emb,
                        raw_json,
                    ),
                )
                synced_count["teachers"] += 1
            except Exception as e:
                print(f"Error inserting teacher {teacher_id}: {e}")

        classes_ref = db_fs.collection("classes").stream()
        for doc in classes_ref:
            data = doc.to_dict()
            class_id = doc.id
            raw_json = json.dumps(data, default=str)
            try:
                # Firestore schema changed: prefer time_start/time_end if available.
                time_start = data.get("time_start") or data.get("timeStart") or None
                time_end = data.get("time_end") or data.get("timeEnd") or None
                time_val = data.get("time") if data.get("time") is not None else None
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO classes (
                        id, name, gradeLevel, section, subjectName,
                        roomId, roomNumber, teacher_id, days, time, time_start, time_end,
                        createdAt, updatedAt, raw_doc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        class_id,
                        data.get("name"),
                        data.get("gradeLevel"),
                        data.get("section"),
                        data.get("subjectName"),
                        data.get("roomId"),
                        data.get("roomNumber"),
                        data.get("teacherId"),
                        data.get("days"),
                        time_val,
                        time_start,
                        time_end,
                        data.get("createdAt"),
                        data.get("updatedAt"),
                        raw_json,
                    ),
                )
                synced_count["classes"] += 1
            except Exception as e:
                print(f"Error inserting class {class_id}: {e}")

        students_ref = db_fs.collection("students").stream()
        for doc in students_ref:
            data = doc.to_dict()
            student_id = doc.id
            profile_url = data.get("profilePicUrl") or data.get("profile_pic_url")
            raw_json = json.dumps(data, default=str)
            emb = None
            if profile_url:
                try:
                    resp = requests.get(profile_url, timeout=15, allow_redirects=True)
                    if resp.status_code == 200:
                        content = resp.content
                        # Save a local copy of the profile image (best-effort)
                        try:
                            local_path = media.save_profile_photo(student_id, 'students', content)
                            if local_path:
                                profile_url = local_path
                        except Exception:
                            pass

                        img = None
                        if cv2 is not None and np is not None:
                            try:
                                img_array = np.asarray(bytearray(content), dtype=np.uint8)
                                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                            except Exception:
                                img = None
                        if img is None and Image is not None:
                            try:
                                pil = Image.open(io.BytesIO(content)).convert('RGB')
                                img = np.asarray(pil)[:, :, ::-1] if np is not None else None
                            except Exception:
                                img = None

                        if img is not None:
                            try:
                                mdl = recognition._init_model() or recognition.model
                                if mdl is not None:
                                    small = cv2.resize(img, (320, 240)) if cv2 is not None else img
                                    try:
                                        faces = mdl.get(small)
                                    except Exception:
                                        faces = []
                                    if faces:
                                        emb = faces[0].embedding.tobytes()
                            except Exception as e:
                                print(f"Model processing failed for student {student_id}: {e}")
                except Exception as e:
                    print(f"Error downloading/processing student {student_id}: {e}")

            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO students (
                        id, firstname, middlename, lastname,
                        school_email, personal_email, guardianname,
                        guardiancontact, status, temp_password, profilePicUrl,
                        createdAt, updatedAt, embedding, raw_doc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        student_id,
                        data.get("firstname"),
                        data.get("middlename"),
                        data.get("lastname"),
                        data.get("school_email"),
                        data.get("personal_email"),
                        data.get("guardianname"),
                        data.get("guardiancontact"),
                        data.get("status"),
                        data.get("temp_password"),
                        profile_url,
                        data.get("createdAt"),
                        data.get("updatedAt"),
                        emb,
                        raw_json,
                    ),
                )
                synced_count["students"] += 1

                classes_arr = data.get("classes") or []
                try:
                    cursor.execute("DELETE FROM class_students WHERE student_id = ?", (student_id,))
                except Exception:
                    pass
                for class_id in classes_arr:
                    try:
                        cursor.execute("INSERT OR IGNORE INTO classes (id, raw_doc) VALUES (?, ?)", (class_id, None))
                        cursor.execute("INSERT OR IGNORE INTO class_students (class_id, student_id) VALUES (?, ?)", (class_id, student_id))
                        synced_count["class_students"] += 1
                    except Exception as e:
                        print(f"Error linking student {student_id} -> class {class_id}: {e}")
            except Exception as e:
                print(f"Error inserting student {student_id}: {e}")

        conn.commit()
        conn.close()

        # reload embeddings
        state.load_embeddings()

        # Also sync attendance_sessions collection into a local table
        try:
            conn = state.get_db()
            cur = conn.cursor()
            # store Firestore attendance documents in a dedicated table to avoid schema conflicts
            cur.execute(
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
                sessions_ref = db_fs.collection("attendance_sessions").stream()
                for doc in sessions_ref:
                    data = doc.to_dict()
                    fs_id = doc.id
                    raw_json = json.dumps(data, default=str)
                    # normalize fields
                    class_id = data.get("classId") or data.get("class_id")
                    teacher_id = data.get("teacherId") or data.get("teacher_id")
                    date = str(data.get("date")) if data.get("date") is not None else None
                    isActive = str(data.get("isActive")) if data.get("isActive") is not None else None
                    roomId = data.get("roomId") or data.get("room_id")
                    studentsPresent = json.dumps(data.get("studentsPresent") or data.get("students_present") or [])
                    studentsAbsent = json.dumps(data.get("studentsAbsent") or data.get("students_absent") or [])
                    timeStarted = str(data.get("timeStarted") or data.get("time_started")) if (data.get("timeStarted") or data.get("time_started")) is not None else None
                    timeEnded = str(data.get("timeEnded") or data.get("time_ended")) if (data.get("timeEnded") or data.get("time_ended")) is not None else None

                    try:
                        cur.execute(
                            "INSERT OR REPLACE INTO attendance_sessions_fs (fs_id, class_id, teacher_id, date, isActive, roomId, studentsPresent, studentsAbsent, timeStarted, timeEnded, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                fs_id,
                                class_id,
                                teacher_id,
                                date,
                                isActive,
                                roomId,
                                studentsPresent,
                                studentsAbsent,
                                timeStarted,
                                timeEnded,
                                raw_json,
                            ),
                        )
                        synced_count["attendance_sessions"] = synced_count.get("attendance_sessions", 0) + 1
                    except Exception as e:
                        print(f"Error inserting attendance_session {fs_id}: {e}")
            except Exception:
                # collection may not exist or be empty
                pass
            conn.commit()
            conn.close()
        except Exception:
            pass

        # Also sync rooms and kiosks collections if available
        try:
            conn = state.get_db()
            cur = conn.cursor()
            # create dedicated tables for rooms and kiosks from Firestore
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rooms_fs (
                    fs_id TEXT PRIMARY KEY,
                    roomname TEXT,
                    kioskid TEXT,
                    assignedteachers JSON,
                    currentsessionid TEXT,
                    isactive TEXT,
                    createdat TEXT,
                    updatedat TEXT,
                    raw_doc JSON
                )
            """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS kiosks_fs (
                    fs_id TEXT PRIMARY KEY,
                    name TEXT,
                    serialNumber TEXT,
                    assignedRoomId TEXT,
                    ipAddress TEXT,
                    macAddress TEXT,
                    status TEXT,
                    installedAt TEXT,
                    updatedAt TEXT,
                    raw_doc JSON
                )
            """
            )

            try:
                rooms_ref = db_fs.collection("rooms").stream()
                room_count = 0
                # determine local kiosk id (if any) so we can notify when a room targeting our kiosk is updated
                try:
                    loc_conn = state.get_db()
                    loc_cur = loc_conn.cursor()
                    loc_cur.execute("SELECT fs_id FROM kiosks_fs LIMIT 1")
                    lk = loc_cur.fetchone()
                    local_kiosk_id = lk[0] if lk and lk[0] else None
                    try:
                        loc_conn.close()
                    except Exception:
                        pass
                except Exception:
                    local_kiosk_id = None
                for doc in rooms_ref:
                    data = doc.to_dict()
                    fs_id = doc.id
                    raw_json = json.dumps(data, default=str)
                    roomname = data.get("roomname") or data.get("name")
                    kioskid = data.get("kioskId") or data.get("kioskid") or data.get("kiosk")
                    assignedteachers = json.dumps(data.get("assignedTeachers") or data.get("assigned_teachers") or [])
                    currentsessionid = data.get("currentsessionId") or data.get("currentsessionid") or data.get("currentsession")
                    isactive = str(data.get("isActive")) if data.get("isActive") is not None else None
                    createdat = str(data.get("createdAt")) if data.get("createdAt") is not None else None
                    updatedat = str(data.get("updatedAt")) if data.get("updatedAt") is not None else None

                    try:
                        cur.execute(
                            "INSERT OR REPLACE INTO rooms_fs (fs_id, roomname, kioskid, assignedteachers, currentsessionid, isactive, createdat, updatedat, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (fs_id, roomname, kioskid, assignedteachers, currentsessionid, isactive, createdat, updatedat, raw_json),
                        )
                        # If this room references our local kiosk, insert a notification
                        try:
                            if local_kiosk_id and kioskid and str(kioskid) == str(local_kiosk_id):
                                try:
                                    from . import kiosk_notifications as kn
                                    # use a human-readable message for details instead of packing the full Firestore doc
                                    msg_ts = updatedat or createdat or time.strftime("%Y-%m-%dT%H:%M:%S%z")
                                    kn.insert_local_and_maybe_remote({
                                        'notif_id': f'sync-room-{fs_id}-{int(time.time())}',
                                        'kiosk_id': local_kiosk_id,
                                        'room': fs_id,
                                        'title': 'Room assignment updated',
                                        'type': 'info',
                                        'details': f"Room assignation was updated successfully at {msg_ts}",
                                        'timestamp': msg_ts,
                                        'createdAt': msg_ts,
                                    })
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        room_count += 1
                    except Exception as e:
                        print(f"Error inserting room {fs_id}: {e}")
                if room_count:
                    synced_count["rooms"] = room_count
            except Exception:
                pass

            try:
                kiosks_ref = db_fs.collection("kiosks").stream()
                kiosk_count = 0
                # determine local kiosk id (if any) so we can notify when this kiosk's doc is updated
                try:
                    loc_conn = state.get_db()
                    loc_cur = loc_conn.cursor()
                    loc_cur.execute("SELECT fs_id FROM kiosks_fs LIMIT 1")
                    lk = loc_cur.fetchone()
                    local_kiosk_id = lk[0] if lk and lk[0] else None
                    try:
                        loc_conn.close()
                    except Exception:
                        pass
                except Exception:
                    local_kiosk_id = None
                for doc in kiosks_ref:
                    data = doc.to_dict()
                    fs_id = doc.id
                    raw_json = json.dumps(data, default=str)
                    name = data.get("name") or data.get("displayName")
                    serial = data.get("serialNumber") or data.get("serial_number") or data.get("serial")
                    assignedRoomId = data.get("assignedRoomId") or data.get("assigned_room_id") or data.get("assignedRoom")
                    ip = data.get("ipAddress") or data.get("ip_address") or data.get("ip")
                    mac = data.get("macAddress") or data.get("mac_address") or data.get("mac")
                    status = data.get("status")
                    installedAt = str(data.get("installedAt")) if data.get("installedAt") is not None else None
                    updatedAt = str(data.get("updatedAt")) if data.get("updatedAt") is not None else None

                    try:
                        cur.execute(
                            "INSERT OR REPLACE INTO kiosks_fs (fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (fs_id, name, serial, assignedRoomId, ip, mac, status, installedAt, updatedAt, raw_json),
                        )
                        # If this Firestore doc corresponds to our local kiosk, insert a notification about the update
                        try:
                            if local_kiosk_id and str(fs_id) == str(local_kiosk_id):
                                try:
                                    from . import kiosk_notifications as kn
                                    msg_ts = updatedAt or installedAt or time.strftime("%Y-%m-%dT%H:%M:%S%z")
                                    kn.insert_local_and_maybe_remote({
                                        'notif_id': f'sync-kiosk-{fs_id}-{int(time.time())}',
                                        'kiosk_id': fs_id,
                                        'room': assignedRoomId,
                                        'title': 'Kiosk configuration updated',
                                        'type': 'success',
                                        'details': f"Kiosk configuration was updated successfully at {msg_ts}",
                                        'timestamp': msg_ts,
                                        'createdAt': msg_ts,
                                    })
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        kiosk_count += 1
                    except Exception as e:
                        print(f"Error inserting kiosk {fs_id}: {e}")
                if kiosk_count:
                    synced_count["kiosks"] = kiosk_count
            except Exception:
                pass

            conn.commit()
            conn.close()
        except Exception:
            pass

        # Include a helpful message when nothing was synced
        message = None
        total_synced = sum(v for v in synced_count.values())
        if total_synced == 0:
            message = "no_records_synced"
        return {"status": "success", "synced": synced_count, "message": message}
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        # Return a concise error to the client, full traceback is in server logs
        return JSONResponse(content={"error": "sync_failed", "detail": str(e)}, status_code=500)


@router.get('/sync/local_reload')
def sync_local_reload():
    """Reload embeddings from the local sqlite DB into memory.

    Useful when Firestore is not configured but you want the recognition
    embeddings refreshed from the last local sync copy.
    """
    try:
        state.load_embeddings()
        return {"status": "ok", "message": "local_embeddings_reloaded"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": "reload_failed", "detail": str(e)}, status_code=500)


# Lightweight background partial sync for selected collections.
# This avoids heavy image/model processing and focuses on updating
# kiosks_fs, students, teachers, classes and class_students links.
import threading
from datetime import datetime, timezone

# incremental sync state
_partial_last_update = {}
_partial_last_run = None
_partial_last_synced = {}

_partial_bg_thread = None
_partial_bg_started = False


def _sync_partial_collections():
    """Pull the target Firestore collections and update local DB tables.

    Returns a dict summary or {'error': ...} on failure.
    """
    if not db_fs:
        return {'error': 'firestore_not_configured'}

    conn = None
    try:
        conn = state.get_db()
        cur = conn.cursor()
        synced = {'students': 0, 'teachers': 0, 'classes': 0, 'kiosks': 0, 'class_students': 0}

        # Teachers (lightweight: do not download/process images)
        try:
            fs_ids = set()
            count = 0
            for doc in db_fs.collection('teachers').stream():
                fs_ids.add(doc.id)
                data = doc.to_dict() or {}
                teacher_id = doc.id
                try:
                    raw_json = json.dumps(data, default=str)
                    cur.execute(
                        "INSERT OR REPLACE INTO teachers (id, firstname, middlename, lastname, school_email, personal_email, status, temp_password, profilePicUrl, createdAt, updatedAt, embedding, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            teacher_id,
                            data.get('firstname'),
                            data.get('middlename'),
                            data.get('lastname'),
                            data.get('school_email'),
                            data.get('personal_email'),
                            data.get('status'),
                            data.get('temp_password'),
                            data.get('profilePicUrl') or data.get('profile_pic_url'),
                            data.get('createdAt'),
                            data.get('updatedAt'),
                            None,
                            raw_json,
                        ),
                    )
                    synced['teachers'] += 1
                    count += 1
                except Exception:
                    pass
            # remove local teachers that are not in Firestore anymore
            try:
                cur.execute("SELECT id FROM teachers")
                local_ids = set([r[0] for r in cur.fetchall() if r and r[0]])
                to_remove = local_ids - fs_ids
                if to_remove:
                    cur.executemany("DELETE FROM teachers WHERE id = ?", [(i,) for i in to_remove])
            except Exception:
                pass
            _partial_last_synced['teachers'] = count
        except Exception:
            pass

        # Classes
        try:
            fs_ids = set()
            count = 0
            for doc in db_fs.collection('classes').stream():
                fs_ids.add(doc.id)
                data = doc.to_dict() or {}
                class_id = doc.id
                try:
                    raw_json = json.dumps(data, default=str)

                    # normalize time fields: Firestore may store Timestamp objects or nested maps
                    def _to_iso(val):
                        if val is None:
                            return None
                        try:
                            # datetime-like objects
                            if hasattr(val, 'isoformat'):
                                return val.isoformat()
                        except Exception:
                            pass
                        try:
                            # some Firestore timestamp classes expose to_datetime or ToDatetime
                            if hasattr(val, 'ToDatetime'):
                                return val.ToDatetime().isoformat()
                            if hasattr(val, 'to_datetime'):
                                return val.to_datetime().isoformat()
                            if hasattr(val, 'ToDatetime') or hasattr(val, 'to_datetime'):
                                return str(val)
                        except Exception:
                            pass
                        # fallback: stringify
                        try:
                            return str(val)
                        except Exception:
                            return None

                    raw_time = data.get('time')
                    # time may be a map {'start':..., 'end':...} or similar
                    time_start = data.get('time_start') or data.get('timeStart') or None
                    time_end = data.get('time_end') or data.get('timeEnd') or None
                    if raw_time and isinstance(raw_time, dict):
                        # prefer explicit keys if present
                        time_start = raw_time.get('start') or raw_time.get('time_start') or time_start
                        time_end = raw_time.get('end') or raw_time.get('time_end') or time_end

                    time_start_s = _to_iso(time_start)
                    time_end_s = _to_iso(time_end)

                    # For the 'time' column, store a JSON string if it's a dict, else ISO/string
                    if isinstance(raw_time, dict):
                        time_val = json.dumps(raw_time, default=str)
                    else:
                        time_val = _to_iso(raw_time) if raw_time is not None else None

                    cur.execute(
                        "INSERT OR REPLACE INTO classes (id, name, gradeLevel, section, subjectName, roomId, roomNumber, teacher_id, days, time, time_start, time_end, createdAt, updatedAt, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            class_id,
                            data.get('name'),
                            data.get('gradeLevel'),
                            data.get('section'),
                            data.get('subjectName'),
                            data.get('roomId'),
                            data.get('roomNumber'),
                            data.get('teacherId'),
                            data.get('days'),
                            time_val,
                            time_start_s,
                            time_end_s,
                            data.get('createdAt'),
                            data.get('updatedAt'),
                            raw_json,
                        ),
                    )
                    synced['classes'] += 1
                    count += 1
                except Exception:
                    pass
            # remove local classes not present in Firestore and clean class_students
            try:
                cur.execute("SELECT id FROM classes")
                local_ids = set([r[0] for r in cur.fetchall() if r and r[0]])
                to_remove = local_ids - fs_ids
                if to_remove:
                    cur.executemany("DELETE FROM classes WHERE id = ?", [(i,) for i in to_remove])
                    cur.executemany("DELETE FROM class_students WHERE class_id = ?", [(i,) for i in to_remove])
            except Exception:
                pass
            _partial_last_synced['classes'] = count
        except Exception:
            pass

        # Students and class_students
        try:
            fs_ids = set()
            count = 0
            for doc in db_fs.collection('students').stream():
                fs_ids.add(doc.id)
                data = doc.to_dict() or {}
                student_id = doc.id
                try:
                    raw_json = json.dumps(data, default=str)
                    cur.execute(
                        "INSERT OR REPLACE INTO students (id, firstname, middlename, lastname, school_email, personal_email, guardianname, guardiancontact, status, temp_password, profilePicUrl, createdAt, updatedAt, embedding, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            student_id,
                            data.get('firstname'),
                            data.get('middlename'),
                            data.get('lastname'),
                            data.get('school_email'),
                            data.get('personal_email'),
                            data.get('guardianname'),
                            data.get('guardiancontact'),
                            data.get('status'),
                            data.get('temp_password'),
                            data.get('profilePicUrl') or data.get('profile_pic_url'),
                            data.get('createdAt'),
                            data.get('updatedAt'),
                            None,
                            raw_json,
                        ),
                    )
                    synced['students'] += 1
                    count += 1

                    # Update class_students
                    classes_arr = data.get('classes') or []
                    try:
                        cur.execute("DELETE FROM class_students WHERE student_id = ?", (student_id,))
                    except Exception:
                        pass
                    for class_id in classes_arr:
                        try:
                            cur.execute("INSERT OR IGNORE INTO classes (id, raw_doc) VALUES (?, ?)", (class_id, None))
                            cur.execute("INSERT OR IGNORE INTO class_students (class_id, student_id) VALUES (?, ?)", (class_id, student_id))
                            synced['class_students'] += 1
                        except Exception:
                            pass
                except Exception:
                    pass
            # remove local students that are not in Firestore and their class links
            try:
                cur.execute("SELECT id FROM students")
                local_ids = set([r[0] for r in cur.fetchall() if r and r[0]])
                to_remove = local_ids - fs_ids
                if to_remove:
                    cur.executemany("DELETE FROM students WHERE id = ?", [(i,) for i in to_remove])
                    cur.executemany("DELETE FROM class_students WHERE student_id = ?", [(i,) for i in to_remove])
            except Exception:
                pass
            _partial_last_synced['students'] = count
        except Exception:
            pass

        # Kiosks
        try:
            fs_ids = set()
            count = 0
            for doc in db_fs.collection('kiosks').stream():
                fs_ids.add(doc.id)
                data = doc.to_dict() or {}
                fs_id = doc.id
                try:
                    raw_json = json.dumps(data, default=str)
                    name = data.get('name') or data.get('displayName')
                    serial = data.get('serialNumber') or data.get('serial_number') or data.get('serial')
                    assignedRoomId = data.get('assignedRoomId') or data.get('assigned_room_id') or data.get('assignedRoom')
                    ip = data.get('ipAddress') or data.get('ip_address') or data.get('ip')
                    mac = data.get('macAddress') or data.get('mac_address') or data.get('mac')
                    status_val = data.get('status')
                    installedAt = str(data.get('installedAt')) if data.get('installedAt') is not None else None
                    updatedAt = str(data.get('updatedAt')) if data.get('updatedAt') is not None else None
                    cur.execute(
                        "INSERT OR REPLACE INTO kiosks_fs (fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (fs_id, name, serial, assignedRoomId, ip, mac, status_val, installedAt, updatedAt, raw_json),
                    )
                    synced['kiosks'] += 1
                    count += 1
                except Exception:
                    pass
            # remove local kiosks that are no longer in Firestore
            try:
                cur.execute("SELECT fs_id FROM kiosks_fs")
                local_ids = set([r[0] for r in cur.fetchall() if r and r[0]])
                to_remove = local_ids - fs_ids
                if to_remove:
                    cur.executemany("DELETE FROM kiosks_fs WHERE fs_id = ?", [(i,) for i in to_remove])
            except Exception:
                pass
            _partial_last_synced['kiosks'] = count
        except Exception:
            pass

        try:
            conn.commit()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

        return {'status': 'ok', 'synced': synced}
    except Exception as e:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return {'error': str(e)}


def _partial_bg_loop(interval):
    print(f'partial background sync started (interval={interval}s)')
    while True:
        try:
            _sync_partial_collections()
        except Exception as e:
            print(f'partial background sync error: {e}')
        try:
            time.sleep(interval)
        except Exception:
            pass


def start_partial_background_sync():
    """Start a daemon thread that polls Firestore for the target collections.

    Controlled by env var ENABLE_BACKGROUND_SYNC (default '1') and interval
    by BACKGROUND_PARTIAL_SYNC_INTERVAL (seconds, default 3).
    """
    global _partial_bg_thread, _partial_bg_started
    try:
        enabled = os.environ.get('ENABLE_BACKGROUND_SYNC', '1')
        try:
            enabled = bool(int(enabled))
        except Exception:
            enabled = str(enabled).lower() in ('1', 'true', 'yes', 'on')
        if not enabled:
            print('partial background sync disabled via ENABLE_BACKGROUND_SYNC')
            return None
    except Exception:
        pass

    if _partial_bg_started:
        return _partial_bg_thread

    try:
        interval = int(os.environ.get('BACKGROUND_PARTIAL_SYNC_INTERVAL', '3'))
    except Exception:
        interval = 3

    try:
        _partial_bg_thread = threading.Thread(target=_partial_bg_loop, args=(interval,), daemon=True)
        _partial_bg_thread.start()
        _partial_bg_started = True
        return _partial_bg_thread
    except Exception as e:
        print(f'failed to start partial background sync: {e}')
        return None
