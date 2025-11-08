from fastapi import APIRouter
from fastapi.responses import JSONResponse
from . import state
import sqlite3

router = APIRouter()


@router.get("/students")
def get_students_by_ids(ids: str = ""):
    """Return student records for a comma-separated list of ids.

    Query param: ids= id1,id2,id3
    Response: { students: [ { id, firstname, lastname } ] }
    """
    try:
        if not ids:
            return {"students": []}
        id_list = [i for i in ids.split(",") if i]
        if not id_list:
            return {"students": []}

        conn = state.get_db()
        cur = conn.cursor()
        # Build a parameter list for SQL IN clause
        placeholders = ",".join(["?" for _ in id_list])
        query = f"SELECT id, firstname, lastname FROM students WHERE id IN ({placeholders})"
        cur.execute(query, tuple(id_list))
        rows = cur.fetchall()
        conn.close()
        students = []
        for r in rows:
            students.append({"id": r[0], "firstname": r[1] or "", "lastname": r[2] or ""})
        return {"students": students}
    except sqlite3.Error as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
