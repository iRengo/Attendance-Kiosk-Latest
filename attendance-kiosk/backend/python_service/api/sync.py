from fastapi import APIRouter
from fastapi.responses import JSONResponse
from . import state
import os
import json
import shutil
import requests

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
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO classes (
                        id, name, gradeLevel, section, subjectName,
                        roomId, roomNumber, teacher_id, days, time,
                        createdAt, updatedAt, raw_doc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        data.get("time"),
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
