from fastapi import APIRouter
from fastapi.responses import StreamingResponse, JSONResponse
import io
import os
from typing import Optional
import threading
import queue
import time

router = APIRouter()

# Optional heavy deps
try:
	import cv2
except Exception:
	cv2 = None

try:
	import numpy as np
except Exception:
	np = None

try:
	import insightface
except Exception:
	insightface = None

from . import state
from . import media

# Module-level camera and model to reuse between requests
_cap = None
model = None

# Live caches updated by the background capture/recognize worker
latest_frame_buf = None
latest_frame_lock = threading.Lock()
latest_teacher_result = {"status": "idle"}
latest_student_result = {"status": "idle"}
_worker_running = False
# small state for unrecognized face signaling (display-only, rate-limited)
latest_unrecognized_result = {"status": "idle"}
_last_unrecog_ts = 0.0
# anti-spoofing / liveness signal
latest_spoof_result = {"status": "idle"}
_last_spoof_ts = 0.0
# lightweight detection cache (faces count + ts)
latest_detection_result = {"faces": 0, "ts": 0.0, "known": False}
TARGET_FPS = int(os.environ.get("CAP_FPS", 15))
# Separate tunables for streaming (jpeg encode) and inference loop
STREAM_FPS = int(os.environ.get("STREAM_FPS", TARGET_FPS))
INFER_FPS = int(os.environ.get("INFER_FPS", max(1, TARGET_FPS // 2)))

# Small in-memory queues to decouple capture -> encode -> inference
# keep queues tiny to prioritize the latest frame; size=1 drops older frames
_encode_q = queue.Queue(maxsize=1)
_infer_q = queue.Queue(maxsize=1)


def _put_drop_old(q, item):
	"""Put item into q; if full, remove the old and put the new one.

	Keep this inexpensive: queue operations are cheap relative to encoding/inference.
	"""
	try:
		q.put_nowait(item)
	except queue.Full:
		try:
			q.get_nowait()
		except Exception:
			pass
		try:
			q.put_nowait(item)
		except Exception:
			pass


def _open_camera():
	global _cap
	if cv2 is None:
		return None
	if _cap is not None and getattr(_cap, "isOpened", lambda: False)():
		return _cap

	cam_index = int(os.environ.get("CAM_INDEX", -1))
	if cam_index >= 0:
		try:
			c = cv2.VideoCapture(cam_index)
			if c is not None and c.isOpened():
				_cap = c
				return _cap
		except Exception:
			pass

	# Respect an explicit device path via CAM_DEVICE (e.g. /dev/video1)
	cam_device = os.environ.get("CAM_DEVICE")
	if cam_device:
		try:
			c = cv2.VideoCapture(cam_device)
			if c is not None and c.isOpened():
				_cap = c
				return _cap
		except Exception:
			pass

	# Only try the explicit CAM_INDEX then /dev/video1 then 0 to avoid long probing delays
	for i in (1, 0):
		try:
			# try numeric index first
			c = cv2.VideoCapture(i)
			if c is not None and c.isOpened():
				_cap = c
				return _cap
			else:
				try:
					c.release()
				except Exception:
					pass
		except Exception:
			continue

	# Finally, try the common device path
	try:
		dev_path = "/dev/video1"
		c = cv2.VideoCapture(dev_path)
		if c is not None and c.isOpened():
			_cap = c
			return _cap
		else:
			try:
				c.release()
			except Exception:
				pass
	except Exception:
		pass
	return None


def _init_model():
	global model
	if insightface is None:
		model = None
		return None
	if model is not None:
		return model
	try:
		appm = insightface.app.FaceAnalysis(name="buffalo_l")
		try:
			appm.prepare(ctx_id=0, det_size=(320, 320))
		except Exception:
			try:
				appm.prepare(ctx_id=-1, det_size=(320, 320))
			except Exception:
				model = None
				return None
		model = appm
		return model
	except Exception:
		model = None
		return None


def _match_face_in_list(emb_list, face_emb, threshold=0.5):
	"""Return best match dict {id,name,score} or None.

	emb_list items: (id, name, np.ndarray)
	"""
	if np is None or not emb_list or face_emb is None:
		return None
	try:
		embs = np.stack([t[2] for t in emb_list])
		sims = np.dot(embs, face_emb) / (np.linalg.norm(embs, axis=1) * np.linalg.norm(face_emb))
		best_idx = int(np.argmax(sims))
		if float(sims[best_idx]) > threshold:
			return {"id": emb_list[best_idx][0], "name": emb_list[best_idx][1], "score": float(sims[best_idx])}
	except Exception:
		return None
	return None


# Three cooperating worker threads to decouple capture, encode, and inference
def _capture_thread():
	"""Continuously read frames from camera and publish to encode+infer queues."""
	global _cap, _worker_running
	_worker_running = True
	interval = 1.0 / max(1, TARGET_FPS)
	cam = None
	while True:
		try:
			if cam is None or not getattr(cam, 'isOpened', lambda: False)():
				cam = _open_camera()

			if cam is None:
				time.sleep(interval)
				continue

			ret, frame = False, None
			try:
				ret, frame = cam.read()
			except Exception:
				ret = False

			if not ret or frame is None:
				# produce a blank frame for encoder to pick up
				if cv2 is not None and np is not None:
					blank = np.zeros((480, 640, 3), dtype=np.uint8)
					_put_drop_old(_encode_q, blank)
					_put_drop_old(_infer_q, blank)
				time.sleep(interval)
				continue

			# put frame into encode and infer queues (drop oldest if busy)
			_put_drop_old(_encode_q, frame)
			_put_drop_old(_infer_q, frame)
			# sleep to target capture FPS
			time.sleep(interval)
		except Exception:
			try:
				time.sleep(0.1)
			except Exception:
				pass


def _encode_thread():
	"""Encode frames to JPEG for the `/camera-feed` endpoint and update latest_frame_buf.

	Uses a blocking get() so we process frames as soon as they arrive without unnecessary timeouts.
	"""
	# If cv2 or numpy missing, this thread will not run (threads only start when cv2 present)
	while True:
		try:
			frame = _encode_q.get()  # block until a frame is available
			if frame is None:
				continue
			try:
				ok, buf = cv2.imencode('.jpg', frame)
				if ok:
					with latest_frame_lock:
						latest_frame_buf = buf.tobytes()
			except Exception:
				# encoding failed; skip
				pass
		except Exception:
			try:
				time.sleep(0.1)
			except Exception:
				pass


def _infer_thread():
	"""Run face model on frames and update cached recognition results.

	Uses blocking get() and a simple rate limiter to respect INFER_FPS without idle timeouts.
	"""
	mdl = None
	try:
		mdl = _init_model()
	except Exception:
		mdl = None

	interval = 1.0 / max(1, INFER_FPS)
	last_infer = 0.0
	while True:
		try:
			frame = _infer_q.get()  # block until a frame is available
			if frame is None or mdl is None or np is None:
				continue

			start = time.time()
			try:
				try:
					small = cv2.resize(frame, (320, 240)) if cv2 is not None else frame
				except Exception:
					small = frame
				faces = mdl.get(small)

				# update detection cache
				now = time.time()
				try:
					latest_detection_result.update({"faces": len(faces) if faces else 0, "ts": now, "known": False})
				except Exception:
					pass

				if not faces or len(faces) == 0:
					# no faces detected: surface this explicitly so UI can react
					try:
						latest_teacher_result.update({"status": "no_face"})
					except Exception:
						pass
					try:
						latest_student_result.update({"status": "no_face"})
					except Exception:
						pass
					try:
						latest_unrecognized_result.update({"status": "idle"})
					except Exception:
						pass
					continue
				# if we continue, detection known stays False (no faces)
			except Exception:
				faces = []

			if faces:
				face = faces[0]
				try:
					emb = face.embedding.astype(np.float32)
				except Exception:
					emb = None

				if emb is not None:
					# teacher match
					try:
						with state.emb_lock:
							tmatch = _match_face_in_list(state.teacher_embeddings, emb)
					except Exception:
						tmatch = None
					if tmatch:
						# include profilePicUrl and determine whether this teacher is assigned to the local kiosk room
						pp = None
						assigned_ok = None
						classes_in_room = []
						conn = None
						try:
							conn = state.get_db()
							cur = conn.cursor()
							# profile pic
							try:
								cur.execute("SELECT profilePicUrl FROM teachers WHERE id = ?", (tmatch["id"],))
								rpic = cur.fetchone()
								if rpic and rpic[0]:
									pp = rpic[0]
							except Exception:
								pp = None

							# build room candidates from kiosks_fs and env
							room_candidates = []
							try:
								cur.execute("SELECT assignedRoomId, raw_doc FROM kiosks_fs LIMIT 1")
								krow = cur.fetchone()
								if krow:
									if krow[0]:
										room_candidates.append(str(krow[0]))
									raw = krow[1] if len(krow) > 1 else None
									if raw:
										try:
											import json as _json
											rj = _json.loads(raw)
											if isinstance(rj, dict):
												if 'roomNumber' in rj:
													room_candidates.append(str(rj.get('roomNumber')))
												if 'assignedRoom' in rj:
													room_candidates.append(str(rj.get('assignedRoom')))
										except Exception:
											pass
							except Exception:
								pass
							try:
								env_room = os.environ.get('KIOSK_ROOM_NUMBER')
								if env_room:
									room_candidates.append(env_room)
							except Exception:
								pass
							room_candidates = [c for c in [str(x).strip() for x in room_candidates if x] if c]

							# If we have candidates, query classes for this teacher filtered by roomNumber
							if room_candidates:
								try:
									placeholders = ",".join(["?"] * len(room_candidates))
									sql = f"SELECT id, name, subjectName, gradeLevel, section, roomNumber FROM classes WHERE teacher_id = ? AND roomNumber IN ({placeholders})"
									params = [tmatch["id"]] + room_candidates
									cur.execute(sql, tuple(params))
									crows = cur.fetchall()
									if crows:
										assigned_ok = True
										for cr in crows:
											classes_in_room.append({"id": cr[0], "name": cr[1], "subjectName": cr[2], "gradeLevel": cr[3], "section": cr[4], "roomNumber": cr[5] if len(cr) > 5 else None})
									else:
										assigned_ok = False
								except Exception:
									assigned_ok = False
							else:
								# no room candidates: leave assigned_ok as None (unknown) and optionally list all classes for this teacher
								try:
									cur.execute("SELECT id, name, subjectName, gradeLevel, section, roomNumber FROM classes WHERE teacher_id = ?", (tmatch["id"],))
									crows = cur.fetchall()
									for cr in crows:
										classes_in_room.append({"id": cr[0], "name": cr[1], "subjectName": cr[2], "gradeLevel": cr[3], "section": cr[4], "roomNumber": cr[5] if len(cr) > 5 else None})
								except Exception:
									pass
						except Exception:
							pass
						finally:
							try:
								if conn:
									conn.close()
							except Exception:
								pass

						# final update: include assigned flag and classes when available
						payload = {"status": "success", "id": tmatch["id"], "name": tmatch["name"], "score": tmatch.get("score"), "profilePicUrl": pp}
						if assigned_ok is True:
							payload["assigned"] = True
							if classes_in_room:
								payload["classes"] = classes_in_room
						elif assigned_ok is False:
							payload["assigned"] = False
						# assigned_ok None -> unknown: omit assigned or set to None
						latest_teacher_result.update(payload)
						# mark detection as known (teacher matched)
						try:
							latest_detection_result.update({"known": True, "ts": time.time()})
						except Exception:
							pass
					else:
						latest_teacher_result.update({"status": "teacher_not_registered"})

					# student match
					try:
						with state.emb_lock:
							smatch = _match_face_in_list(state.student_embeddings, emb)
					except Exception:
						smatch = None
					if smatch:
						student_id = smatch["id"]
						student_name = smatch["name"]
						# enforce session active and registration before accepting
						conn = None
						try:
							conn = state.get_db()
							cur = conn.cursor()
							active_class_id = state.current_session.get("class_id")
							if not active_class_id:
								# no active session: don't accept student
								latest_student_result.update({"status": "service_inactive"})
							else:
								cur.execute("SELECT 1 FROM class_students WHERE class_id = ? AND student_id = ?", (active_class_id, student_id))
								row = cur.fetchone()
								if row:
									# include profilePicUrl from DB if available and save snapshot
									pp = None
									try:
										conn = state.get_db()
										cur = conn.cursor()
										cur.execute("SELECT profilePicUrl FROM students WHERE id = ?", (student_id,))
										row = cur.fetchone()
										if row and row[0]:
											pp = row[0]
										conn.close()
									except Exception:
										try:
											if conn:
												conn.close()
										except Exception:
											pass
									latest_student_result.update({"status": "success", "id": student_id, "name": student_name, "registered": True, "profilePicUrl": pp})
									# mark detection as known (student matched)
									try:
										latest_detection_result.update({"known": True, "ts": time.time()})
									except Exception:
										pass
								else:
									# student not registered for the active class
									latest_student_result.update({"status": "denied", "reason": "not_registered", "id": student_id, "name": student_name, "registered": False})
						except Exception:
							latest_student_result.update({"status": "unknown"})
						finally:
							try:
								if conn:
									conn.close()
							except Exception:
								pass
					else:
						latest_student_result.update({"status": "unknown"})

					# ensure detection-known info reflects any teacher/student match (covers service_inactive cases)
					try:
						known = None
						if tmatch:
							known = {"type": "teacher", "id": tmatch.get("id"), "name": tmatch.get("name"), "score": tmatch.get("score")}
						elif smatch:
							known = {"type": "student", "id": smatch.get("id"), "name": smatch.get("name"), "score": smatch.get("score")}
						if known is not None:
							try:
								latest_detection_result.update({"known": known, "ts": time.time()})
							except Exception:
								pass
					except Exception:
						pass

					# Unrecognized face: neither teacher nor student matched.
					# Rate-limit notifications/signals so the UI isn't flooded.
					try:
						now = time.time()
						try:
							quiet = int(os.environ.get("UNRECOG_QUIET_SECONDS", "5"))
						except Exception:
							quiet = 5
						# if neither matched and embedding exists, set unrecognized signal
						if (not tmatch) and (not smatch) and emb is not None:
							if now - _last_unrecog_ts > quiet:
								_last_unrecog_ts = now
								try:
									latest_unrecognized_result.update({"status": "unrecognized", "ts": now})
								except Exception:
									pass
						else:
							# if matched, clear unrecognized signal
							try:
								latest_unrecognized_result.update({"status": "idle"})
							except Exception:
								pass

						# Anti-spoof / liveness check (anti_fake1). If the face object or
						# its extra attributes include an `anti_fake1` flag, expose it via
						# latest_spoof_result so frontends can show a UI warning.
						try:
							# robustly attempt to read anti_fake1 from face attributes
							anti_flag = None
							try:
								anti_flag = getattr(face, "anti_fake1", None)
							except Exception:
								anti_flag = None
							# some runtimes may put extra attributes in a dict-like field
							try:
								if anti_flag is None and hasattr(face, "extra"):
									ex = getattr(face, "extra")
									if isinstance(ex, dict) and "anti_fake1" in ex:
										anti_flag = ex.get("anti_fake1")
							except Exception:
								pass
							# If we found a truthy anti_fake1 indicator, flag spoof
								if anti_flag:
									try:
										latest_spoof_result.update({"status": "spoof", "ts": now, "method": "anti_fake1"})
									except Exception:
										pass
							else:
								# clear spoof when anti_fake1 not present
								try:
									latest_spoof_result.update({"status": "idle"})
								except Exception:
									pass
						except Exception:
							# swallow any errors reading spoof attributes
							pass
					except Exception:
						# ignore unrecognized signaling failures
						pass

			# rate limit inference to roughly INFER_FPS
			elapsed = time.time() - start
			to_sleep = interval - elapsed
			if to_sleep > 0:
				try:
					time.sleep(to_sleep)
				except Exception:
					pass
			last_infer = time.time()
		except Exception:
			try:
				time.sleep(0.1)
			except Exception:
				pass


# start worker threads (best-effort)
try:
	# only start threads if cv2 is present; otherwise endpoints will return errors as before
	if cv2 is not None:
		threading.Thread(target=_capture_thread, daemon=True).start()
		threading.Thread(target=_encode_thread, daemon=True).start()
		threading.Thread(target=_infer_thread, daemon=True).start()
except Exception:
	pass


@router.get("/camera-feed")
def camera_feed():
	"""Return a single JPEG frame from the camera. If camera or cv2 missing,
	returns JSON error or a blank image where possible.
	"""
	# Prefer cached latest frame for low-latency delivery
	try:
		with latest_frame_lock:
			buf = latest_frame_buf
		if buf:
			return StreamingResponse(io.BytesIO(buf), media_type='image/jpeg')
		# If no cached frame yet, fall back to quick camera probe / blank
		cap = _open_camera()
		if cap is None:
			if cv2 is None or np is None:
				return JSONResponse(content={"error": "camera_unavailable"}, status_code=503)
			blank = np.zeros((480, 640, 3), dtype=np.uint8)
			ok, buf2 = cv2.imencode('.jpg', blank)
			if not ok:
				return JSONResponse(content={"error": "failed_to_encode_fallback"}, status_code=500)
			return StreamingResponse(io.BytesIO(buf2.tobytes()), media_type='image/jpeg')
		# final attempt: read one frame quickly
		ret, frame = False, None
		try:
			ret, frame = cap.read()
		except Exception:
			ret = False
		if not ret or frame is None:
			blank = np.zeros((480, 640, 3), dtype=np.uint8) if (cv2 is not None and np is not None) else None
			if blank is None:
				return JSONResponse(content={"error": "camera_unavailable"}, status_code=503)
			ok, buf2 = cv2.imencode('.jpg', blank)
			if not ok:
				return JSONResponse(content={"error": "failed_to_encode_fallback"}, status_code=500)
			return StreamingResponse(io.BytesIO(buf2.tobytes()), media_type='image/jpeg')
		ok, buf2 = cv2.imencode('.jpg', frame)
		if not ok:
			return JSONResponse(content={"error": "failed_to_encode_frame"}, status_code=500)
		return StreamingResponse(io.BytesIO(buf2.tobytes()), media_type='image/jpeg')
	except Exception as e:
		return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/recognize-teacher")
def recognize_teacher():
	"""Capture a frame, run face model, and attempt to match a teacher.
	Returns JSON with status and optional classes list when teacher matched.
	"""
	# Return latest cached teacher result for instant response
	try:
		res = dict(latest_teacher_result)
		# include detection info so frontends can act on presence quickly
		try:
			res["detected"] = int(latest_detection_result.get("faces", 0))
			res["detected_ts"] = float(latest_detection_result.get("ts", 0.0))
			res["detected_known"] = bool(latest_detection_result.get("known", False))
		except Exception:
			pass
		# include known info (student/teacher) when available
		try:
			res["known"] = latest_detection_result.get("known")
		except Exception:
			pass
		# enrich with profilePicUrl from local DB when available
		try:
			if res.get("status") == "success" and res.get("id"):
				conn = state.get_db()
				try:
					cur = conn.cursor()
					cur.execute("SELECT profilePicUrl FROM teachers WHERE id = ?", (res.get("id"),))
					row = cur.fetchone()
					if row and row[0]:
						res["profilePicUrl"] = row[0]
				finally:
					try:
						conn.close()
					except Exception:
						pass
		except Exception:
			pass
		return res
	except Exception as e:
		return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/recognize-camera")
def recognize_camera():
	"""Recognize a student from the camera. If a class is active in
	`state.current_session` the student must belong to that class.
	"""
	# Return latest cached student result for instant response
	try:
		res = dict(latest_student_result)
		# include detection info so frontends can act on presence quickly
		try:
			res["detected"] = int(latest_detection_result.get("faces", 0))
			res["detected_ts"] = float(latest_detection_result.get("ts", 0.0))
			res["detected_known"] = bool(latest_detection_result.get("known", False))
		except Exception:
			pass
		# include known info (student/teacher) when available
		try:
			res["known"] = latest_detection_result.get("known")
		except Exception:
			pass
		# enrich with profilePicUrl from local DB when available
		try:
			if res.get("status") == "success" and res.get("id"):
				conn = state.get_db()
				try:
					cur = conn.cursor()
					cur.execute("SELECT profilePicUrl FROM students WHERE id = ?", (res.get("id"),))
					row = cur.fetchone()
					if row and row[0]:
						res["profilePicUrl"] = row[0]
				finally:
					try:
						conn.close()
					except Exception:
						pass
		except Exception:
			pass
		return res
	except Exception as e:
		return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/unrecognized")
def unrecognized_status():
	"""Return a tiny display-only object describing the last unrecognized detection.

	This is intentionally lightweight: frontend uses it to show a short-lived banner.
	"""
	try:
		return dict(latest_unrecognized_result)
	except Exception as e:
		return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/anti_spoof")
def anti_spoof_status():
	"""Return a tiny object describing last anti-spoof / liveness signal."""
	try:
		return dict(latest_spoof_result)
	except Exception as e:
		return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/detect")
def detect_status():
	"""Return recent face detection summary: number of faces and timestamp.

	Frontend should poll this for quick presence indication.
	"""
	try:
		return dict(latest_detection_result)
	except Exception as e:
		return JSONResponse(content={"error": str(e)}, status_code=500)
