import os
import sqlite3
import threading
from typing import List, Tuple, Optional

try:
    import numpy as np
except Exception:
    np = None

# Path to the local sqlite DB file
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "data", "db", "local_database.db"))


def get_db() -> sqlite3.Connection:
    """Return a sqlite3 connection and ensure schema exists.

    The function creates parent directories if needed and ensures tables
    used by the app exist. It's safe to call repeatedly.
    """
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Create required tables if they don't exist
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY,
            firstname TEXT,
            middlename TEXT,
            lastname TEXT,
            personal_email TEXT,
            school_email TEXT,
            guardianname TEXT,
            guardiancontact TEXT,
            status TEXT,
            temp_password TEXT,
            profilePicUrl TEXT,
            createdAt TEXT,
            updatedAt TEXT,
            embedding BLOB,
            raw_doc JSON
        )
    """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS teachers (
            id TEXT PRIMARY KEY,
            firstname TEXT,
            middlename TEXT,
            lastname TEXT,
            personal_email TEXT,
            school_email TEXT,
            status TEXT,
            temp_password TEXT,
            profilePicUrl TEXT,
            createdAt TEXT,
            updatedAt TEXT,
            embedding BLOB,
            raw_doc JSON
        )
    """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS classes (
            id TEXT PRIMARY KEY,
            name TEXT,
            gradeLevel TEXT,
            section TEXT,
            subjectName TEXT,
            roomId TEXT,
            roomNumber TEXT,
            teacher_id TEXT,
            days TEXT,
            time TEXT,
            time_start TEXT,
            time_end TEXT,
            createdAt TEXT,
            updatedAt TEXT,
            raw_doc JSON,
            FOREIGN KEY(teacher_id) REFERENCES teachers(id)
        )
    """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS class_students (
            class_id TEXT,
            student_id TEXT,
            PRIMARY KEY (class_id, student_id),
            FOREIGN KEY (class_id) REFERENCES classes(id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """
    )

    # Kiosk notifications table: local cache of kiosk-generated alerts/events
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kiosk_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notif_id TEXT UNIQUE,
            kiosk_id TEXT,
            room TEXT,
            title TEXT,
            type TEXT,
            details TEXT,
            timestamp TEXT,
            createdAt TEXT,
            sync_status TEXT DEFAULT 'pending',
            fs_id TEXT
        )
    """
    )

    # Add optional metadata columns if they don't already exist (safe to run repeatedly)
    try:
        conn.execute("ALTER TABLE kiosk_notifications ADD COLUMN attempts INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE kiosk_notifications ADD COLUMN last_attempt_at TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE kiosk_notifications ADD COLUMN last_error TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE kiosk_notifications ADD COLUMN last_notified_at TEXT")
    except Exception:
        pass

    return conn


# In-memory state caches populated by load_embeddings()
# Each entry: (id, display_name, np.ndarray)
student_embeddings: List[Tuple[str, str, object]] = []
teacher_embeddings: List[Tuple[str, str, object]] = []
emb_lock = threading.Lock()

# lightweight session holder (kept for compatibility with recognition)
current_session = {
    "teacher_id": None,
    "teacher_name": None,
    "class_id": None,
    "class_name": None,
}


def load_embeddings():
    """Load embeddings from the sqlite DB into the in-memory lists.

    If numpy is not available or embeddings are missing, lists become empty.
    """
    global student_embeddings, teacher_embeddings
    if np is None:
        student_embeddings = []
        teacher_embeddings = []
        return

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, firstname, lastname, embedding FROM students")
        rows = cur.fetchall()
        students = []
        for row_id, firstname, lastname, emb_blob in rows:
            if emb_blob:
                try:
                    emb = np.frombuffer(emb_blob, dtype=np.float32)
                    students.append((row_id, f"{firstname or ''} {lastname or ''}".strip(), emb))
                except Exception:
                    continue

        cur.execute("SELECT id, firstname, lastname, embedding FROM teachers")
        rows = cur.fetchall()
        teachers = []
        for row_id, firstname, lastname, emb_blob in rows:
            if emb_blob:
                try:
                    emb = np.frombuffer(emb_blob, dtype=np.float32)
                    teachers.append((row_id, f"{firstname or ''} {lastname or ''}".strip(), emb))
                except Exception:
                    continue
    finally:
        conn.close()

    with emb_lock:
        student_embeddings = students
        teacher_embeddings = teachers
