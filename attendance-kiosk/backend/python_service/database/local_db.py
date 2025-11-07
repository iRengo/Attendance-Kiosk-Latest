# backend/python_service/database/local_db.py
import sqlite3
import numpy as np

DB_PATH = "data/db/local_database.db"

def get_all_embeddings():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, embedding FROM students")
    rows = cursor.fetchall()
    conn.close()

    known_ids, known_names, known_embeddings = [], [], []
    for row in rows:
        id, name, emb_blob = row
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        known_ids.append(id)
        known_names.append(name)
        known_embeddings.append(emb)
    return known_ids, known_names, np.array(known_embeddings)
