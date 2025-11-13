("""Registry endpoints to expose rooms and kiosks data that are synced from Firestore.

These read from local `rooms_fs` and `kiosks_fs` tables which are populated by the sync routine.
""")
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from . import state

router = APIRouter()


def _rows_to_dicts(cursor, rows):
	cols = [c[0] for c in cursor.description]
	results = []
	for r in rows:
		d = {}
		for i, v in enumerate(r):
			d[cols[i]] = v
		results.append(d)
	return results


@router.get("/rooms")
def get_rooms(kioskid: str = Query(None)):
	try:
		conn = state.get_db()
		cur = conn.cursor()
		if kioskid:
			cur.execute("SELECT * FROM rooms_fs WHERE kioskId = ?", (kioskid,))
		else:
			cur.execute("SELECT * FROM rooms_fs")
		rows = cur.fetchall()
		return {"rooms": _rows_to_dicts(cur, rows)}
	except Exception as e:
		return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/kiosks")
def get_kiosks(serial: str = Query(None), kioskid: str = Query(None)):
	try:
		conn = state.get_db()
		cur = conn.cursor()
		if serial:
			cur.execute("SELECT * FROM kiosks_fs WHERE serialNumber = ?", (serial,))
		elif kioskid:
			cur.execute("SELECT * FROM kiosks_fs WHERE fs_id = ?", (kioskid,))
		else:
			cur.execute("SELECT * FROM kiosks_fs")
		rows = cur.fetchall()
		return {"kiosks": _rows_to_dicts(cur, rows)}
	except Exception as e:
		return JSONResponse(content={"error": str(e)}, status_code=500)

