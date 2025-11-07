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
						# include profilePicUrl from DB if available
						pp = None
						try:
							conn = state.get_db()
							cur = conn.cursor()
							cur.execute("SELECT profilePicUrl FROM teachers WHERE id = ?", (tmatch["id"],))
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
						latest_teacher_result.update({"status": "success", "id": tmatch["id"], "name": tmatch["name"], "score": tmatch.get("score"), "profilePicUrl": pp})
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
