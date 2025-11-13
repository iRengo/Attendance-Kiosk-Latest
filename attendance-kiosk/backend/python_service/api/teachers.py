from fastapi import APIRouter
from fastapi.responses import JSONResponse
from . import state
import sqlite3

router = APIRouter()


@router.get("/teachers")
def get_teachers_by_ids(ids: str = ""):
    """Return teacher records for a comma-separated list of ids.

    Query param: ids= id1,id2,id3
    Response: { teachers: [ { id, firstname, lastname } ] }
    """
    try:
        if not ids:
            return {"teachers": []}
        id_list = [i for i in ids.split(",") if i]
        if not id_list:
            return {"teachers": []}

        conn = state.get_db()
        cur = conn.cursor()
        placeholders = ",".join(["?" for _ in id_list])
        query = f"SELECT id, firstname, lastname, profilePicUrl FROM teachers WHERE id IN ({placeholders})"
        cur.execute(query, tuple(id_list))
        rows = cur.fetchall()
        conn.close()
        teachers = []
        for r in rows:
            # r[3] may be a local path like /photos/teachers/<id>.jpg or an absolute URL
            teachers.append({"id": r[0], "firstname": r[1] or "", "lastname": r[2] or "", "profilePicUrl": r[3] or ""})
        return {"teachers": teachers}
    except sqlite3.Error as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
