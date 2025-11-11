import React, { useRef, useEffect, useState } from "react";
import axios from "axios";

// Base URL for backend API. Allow override with Vite env var VITE_API_BASE
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function CameraFeed() {
  const imgRef = useRef(null);
  const lastUrl = useRef(null);
  const [sessionInfo, setSessionInfo] = useState(null);
  const [teacherDetected, setTeacherDetected] = useState(null);
  const lastTeacherRef = useRef(null);
  const [showClassModal, setShowClassModal] = useState(false);
  const [classesList, setClassesList] = useState([]);
  const [selectedClass, setSelectedClass] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const [showStopConfirm, setShowStopConfirm] = useState(false);
  const [stopPending, setStopPending] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [teacherRegistered, setTeacherRegistered] = useState(null); // null=unknown, true/false known
  const stopTimerRef = useRef(null);
  const prevSessionRef = useRef(null);
  // recognition stability: require person to hold still for ~1.5s
  const recognitionStartRef = useRef(null);
  const recognitionClearTimerRef = useRef(null);

  // Check whether the recognized teacher is registered/assigned to this kiosk's room
  useEffect(() => {
    let mounted = true;
    const checkRegistration = async () => {
      // reset if no teacher recognized
      if (!teacherDetected) {
        if (mounted) setTeacherRegistered(null);
        return;
      }

      try {
        // 1) get device info to resolve assignedRoomId
        const dres = await axios.get(`${API_BASE}/device/info`);
        const dk = (dres.data && (dres.data.kiosk || dres.data.device)) || dres.data || null;
        const assigned = dk && (dk.assignedRoomId ?? dk.assignedRoom ?? dk.roomId ?? dk.assignedRoomName);

        // 2) fetch rooms and find matching room by fs_id or kiosk linkage
        let rooms = [];
        try {
          // try kiosk-specific query first (if we have a kiosk id)
          const kioskId = dk && (dk.id || dk.fs_id || dk.kioskId);
          if (kioskId) {
            const rres = await axios.get(`${API_BASE}/rooms?kioskid=${encodeURIComponent(kioskId)}`);
            rooms = (rres.data && rres.data.rooms) || [];
          }
        } catch (e) {
          // fallthrough to global rooms query
        }

        if ((!rooms || rooms.length === 0) && assigned) {
          try {
            const rres2 = await axios.get(`${API_BASE}/rooms`);
            rooms = (rres2.data && rres2.data.rooms) || [];
          } catch (e) {
            rooms = [];
          }
        }

        // find the room that matches assignedRoomId if present, otherwise try first room
        let matched = null;
        if (assigned && rooms && rooms.length > 0) {
          matched = rooms.find((r) => String(r.fs_id) === String(assigned) || String(r.fs_id) === String(assigned));
        }
        if (!matched && rooms && rooms.length > 0) matched = rooms[0];

        // determine if teacher id appears in assignedteachers JSON or in raw_doc
        let registered = null;
        if (matched) {
          try {
            const at = matched.assignedteachers || matched.assignedTeachers || null;
            if (at) {
              let arr = [];
              try { arr = JSON.parse(at); } catch (e) { arr = Array.isArray(at) ? at : [] }
              registered = arr.map((x) => String(x)).includes(String(teacherDetected.id));
            }
            // fallback: check raw_doc string for teacher id (best-effort)
            if (!registered && matched.raw_doc && typeof matched.raw_doc === 'string') {
              registered = String(matched.raw_doc).indexOf(String(teacherDetected.id)) !== -1;
            }
          } catch (e) {
            registered = null;
          }
        }

        if (mounted) setTeacherRegistered(registered === true ? true : false);
      } catch (e) {
        if (mounted) setTeacherRegistered(null);
      }
    };

    checkRegistration();
    return () => { mounted = false; };
  }, [teacherDetected]);
  const [toast, setToast] = useState(null);
  const toastTimerRef = useRef(null);
  const [presentStudentIds, setPresentStudentIds] = useState([]);
  const [presentStudents, setPresentStudents] = useState([]);
  const presentIdsRef = useRef([]);
  const [unrecognizedDetected, setUnrecognizedDetected] = useState(false);
  const [detectCount, setDetectCount] = useState(0);
  const [studentDetected, setStudentDetected] = useState(null);

  useEffect(() => {
    let canceled = false;

    const fetchFrame = async () => {
      try {
        const res = await axios.get(`${API_BASE}/camera-feed`, { responseType: "blob", timeout: 5000 });
        if (canceled) return;
        const blob = res.data;
        const imgUrl = URL.createObjectURL(blob);
        // revoke previous object URL to avoid memory leak
        if (lastUrl.current) URL.revokeObjectURL(lastUrl.current);
        lastUrl.current = imgUrl;
        if (imgRef.current) imgRef.current.src = imgUrl;
      } catch (err) {
        // show nothing; avoid spamming console in case of frequent errors
        console.debug("Camera feed error:", err && err.message ? err.message : err);
      }
      // schedule next frame (approx 15 FPS)
      if (!canceled) setTimeout(fetchFrame, 66);
    };

    fetchFrame(); // start the loop
    return () => {
      canceled = true;
      if (lastUrl.current) {
        try { URL.revokeObjectURL(lastUrl.current); } catch (e) {}
      }
    };
  }, []);

  // Poll session and teacher recognition independently for overlay status
  useEffect(() => {
    let mounted = true;
    const fetchSession = async () => {
      try {
        const res = await axios.get(`${API_BASE}/session`);
        if (!mounted) return;
        setSessionInfo(res.data && res.data.session ? res.data.session : null);
      } catch (e) {
        // ignore
      }
    };
    const fetchTeacher = async () => {
      try {
        const res = await axios.get(`${API_BASE}/recognize-teacher`);
        if (!mounted) return;
        const data = res.data || {};
        // Persist the last recognized teacher until a different teacher is recognized.
        if (data && data.status === "success" && data.id) {
          // if no previous or different id, update; otherwise keep previous
          if (!lastTeacherRef.current || String(lastTeacherRef.current.id) !== String(data.id)) {
            lastTeacherRef.current = data;
            setTeacherDetected(data);
          }
        } else {
          // don't immediately clear on transient no-face/noise; only clear when the session ends
          // however, if there is no active session, clear immediately
          if (!(sessionInfo && sessionInfo.class_id)) {
            lastTeacherRef.current = null;
            setTeacherDetected(null);
          }
        }
      } catch (e) {
        // ignore
      }
    };

    fetchSession();
    fetchTeacher();
    const sid = setInterval(fetchSession, 3000);
    const tid = setInterval(fetchTeacher, 1500);
    return () => { mounted = false; clearInterval(sid); clearInterval(tid); };
  }, []);

  // Poll for unrecognized face signal (display-only). Keep this separate
  // from the teacher/student polls so we don't affect their timing.
  useEffect(() => {
    let mounted = true;
    const pollUnrecognized = async () => {
      try {
        const res = await axios.get(`${API_BASE}/unrecognized`);
        if (!mounted) return;
        const d = res.data || {};
        const now = Date.now() / 1000;
        if (d && d.status === 'unrecognized' && d.ts && (now - d.ts) < 10) {
          setUnrecognizedDetected(true);
        } else {
          setUnrecognizedDetected(false);
        }
      } catch (e) {
        if (mounted) setUnrecognizedDetected(false);
      }
    };
    pollUnrecognized();
    const uid = setInterval(pollUnrecognized, 1200);

    // also poll /detect for immediate face presence updates
    const pollDetect = async () => {
      try {
        const r = await axios.get(`${API_BASE}/detect`);
        if (!mounted) return;
        const dd = r.data || {};
        setDetectCount(Number(dd.faces || 0));
      } catch (e) {
        if (mounted) setDetectCount(0);
      }
    };
    pollDetect();
    const did = setInterval(pollDetect, 700);

    // also poll recognize-camera to see if there's a student match (fast)
    const pollStudent = async () => {
      try {
        const r2 = await axios.get(`${API_BASE}/recognize-camera`);
        if (!mounted) return;
        setStudentDetected(r2.data || null);
      } catch (e) {
        if (mounted) setStudentDetected(null);
      }
    };
    pollStudent();
    const sid2 = setInterval(pollStudent, 800);

    return () => { mounted = false; clearInterval(uid); clearInterval(did); clearInterval(sid2); };
  }, []);

  // require stability (hold-still) before declaring an unrecognized face
  useEffect(() => {
    let mounted = true;
    // clear any existing clear timer
    try {
      if (recognitionClearTimerRef.current) {
        clearTimeout(recognitionClearTimerRef.current);
        recognitionClearTimerRef.current = null;
      }
    } catch (e) {}

    // If there's an active session or stopPending, reset
    if (sessionInfo && sessionInfo.class_id) {
      recognitionStartRef.current = null;
      return () => { mounted = false; };
    }

    // If a face is detected and it's not a pre-session student match, start/continue the stability timer
    const isPreSessionStudent = studentDetected && (studentDetected.status === 'success' || studentDetected.known);
    if (detectCount > 0 && !isPreSessionStudent) {
      if (!recognitionStartRef.current) {
        recognitionStartRef.current = Date.now();
      } else {
        const elapsed = Date.now() - recognitionStartRef.current;
        if (elapsed >= 1500) {
          // after 1.5s of continuous detection, if no teacher/student match exists, mark unrecognized
          if (!(teacherDetected && teacherDetected.status === 'success') && !(studentDetected && studentDetected.status === 'success')) {
            // set local unrecognized indicator (this will also be set by backend in some cases)
            setUnrecognizedDetected(true);
            // clear after 3s so banner isn't permanent
            try {
              recognitionClearTimerRef.current = setTimeout(() => { try { setUnrecognizedDetected(false); } catch (e) {} }, 3000);
            } catch (e) {}
            // reset start so we don't retrigger immediately
            recognitionStartRef.current = null;
          }
        }
      }
    } else {
      // no face or pre-session student: reset stability tracking
      recognitionStartRef.current = null;
    }

    return () => { mounted = false; };
  }, [detectCount, teacherDetected, studentDetected, sessionInfo, stopPending]);

  // Poll current attendance (list of present student IDs) and resolve names from backend
  useEffect(() => {
    let mounted = true;
    const fetchAttendanceAndNames = async () => {
      try {
        // fetch present IDs from backend
        const att = await axios.get(`${API_BASE}/session/attendance`);
        if (!mounted) return;
        const data = att.data || {};
        const ids = Array.isArray(data.studentsPresent) ? data.studentsPresent : [];
        // If ids unchanged, do nothing
        const same = JSON.stringify(ids) === JSON.stringify(presentIdsRef.current);
        if (same) return;
        presentIdsRef.current = ids;
        setPresentStudentIds(ids);

        if (ids.length === 0) {
          setPresentStudents([]);
          return;
        }

        // batch fetch student names
        try {
          const q = encodeURIComponent(ids.join(","));
          const res = await axios.get(`${API_BASE}/students?ids=${q}`);
          const students = (res.data && res.data.students) || [];
          // map to preserve order of ids
          const byId = {};
          students.forEach((s) => {
            byId[String(s.id)] = s;
          });
          const ordered = ids.map((id) => {
            const s = byId[String(id)];
            if (s) {
              return { id: id, firstname: s.firstname || "", lastname: s.lastname || "", name: `${(s.firstname || "").trim()} ${(s.lastname || "").trim()}`.trim() };
            }
            // fallback: show id if name not available
            return { id: id, firstname: "", lastname: "", name: id };
          });
          setPresentStudents(ordered);
        } catch (e) {
          // if name lookup fails, at least show ids
          setPresentStudents(ids.map((id) => ({ id, name: id })));
        }
      } catch (e) {
        // ignore polling errors
      }
    };

    // poll periodically while mounted
    fetchAttendanceAndNames();
    const iid = setInterval(fetchAttendanceAndNames, 1500);
    return () => {
      mounted = false;
      clearInterval(iid);
    };
  }, []);

  // derive overlay state
  // Three-phase behavior when no active session:
  //  - default: "Detecting faces..."
  //  - when a face is present (and it's NOT a known student before session): "Recognizing face..."
  //  - if a student face is detected before a session is active, keep showing "Detecting faces..." (ignore student matches)
  let overlay = { state: "ready", label: "Detecting faces..." };
  if (stopPending) {
    overlay = { state: "pending_stop", label: "Scan face to stop service" };
  } else if (sessionInfo && sessionInfo.class_id) {
    overlay = { state: "active", label: "Active" };
  } else if (teacherDetected && teacherRegistered === false) {
    overlay = { state: "not_registered", label: "You are not registered in this room" };
  } else if (teacherDetected) {
    overlay = { state: "recognized", label: teacherDetected.name || "Teacher" };
  } else if (
    // show "Recognizing face..." only when there is at least one detected face
    // and that detection isn't a pre-session student match (we ignore student faces before session)
    detectCount > 0 &&
    !(studentDetected && (studentDetected.status === 'success' || studentDetected.known))
  ) {
    overlay = { state: "recognizing", label: "Recognizing face..." };
  }

  const circleClass = {
    ready: "bg-white",
    recognizing: "bg-yellow-300",
    recognized: "bg-yellow-400",
    active: "bg-red-500",
    pending_stop: "bg-blue-400",
    not_registered: "bg-red-500",
  }[overlay.state];

  const textClass = {
    ready: "text-white",
    recognizing: "text-yellow-300",
    recognized: "text-yellow-400",
    active: "text-green-400",
    pending_stop: "text-blue-400",
    not_registered: "text-red-400",
  }[overlay.state];

  const borderClass = {
    ready: "border-white",
    recognizing: "border-yellow-300",
    recognized: "border-yellow-400",
    active: "border-green-400",
    pending_stop: "border-blue-400",
    not_registered: "border-red-400",
  }[overlay.state];

  const openClassModal = async () => {
    if (!teacherDetected) return;
    try {
      const res = await axios.get(`${API_BASE}/session/classes?teacher_id=${encodeURIComponent(teacherDetected.id)}`);
      const cls = (res.data && res.data.classes) || [];
      setClassesList(cls);
      setSelectedClass(cls.length > 0 ? cls[0].id : "");
      // fire an update event so RoomInfo can refresh immediately (or accept the assignedRoomId from detail)
      try {
        const dres = await axios.get(`${API_BASE}/device/info`);
        const dk = (dres.data && (dres.data.kiosk || dres.data.device)) || dres.data || null;
        const assigned = dk && (dk.assignedRoomId ?? dk.assignedRoom ?? dk.roomId ?? dk.assignedRoomName);
        window.dispatchEvent(new CustomEvent('kioskAssignedUpdated', { detail: { assignedRoomId: assigned } }));
      } catch (e) {
        // best-effort: still open modal
      }
      setShowClassModal(true);
    } catch (e) {
      console.error("Failed to fetch classes", e);
      setClassesList([]);
      setSelectedClass("");
      setShowClassModal(true);
    }
  };

  const startService = async () => {
    if (!selectedClass || !teacherDetected) return;
    setIsStarting(true);
    try {
      const cls = classesList.find((c) => c.id === selectedClass) || {};
      await axios.post(`${API_BASE}/session/start`, {
        teacher_id: teacherDetected.id,
        teacher_name: teacherDetected.name,
        class_id: cls.id,
        class_name: cls.name || cls.subjectName
      });
      // refresh session
      const res = await axios.get(`${API_BASE}/session`);
      setSessionInfo(res.data && res.data.session ? res.data.session : null);
      setShowClassModal(false);
      setToast("Service started");
      // notify RoomInfo immediately after a successful start (assigned room likely present)
      try {
        const dres2 = await axios.get(`${API_BASE}/device/info`);
        const dk2 = (dres2.data && (dres2.data.kiosk || dres2.data.device)) || dres2.data || null;
        const assigned2 = dk2 && (dk2.assignedRoomId ?? dk2.assignedRoom ?? dk2.roomId ?? dk2.assignedRoomName);
        window.dispatchEvent(new CustomEvent('kioskAssignedUpdated', { detail: { assignedRoomId: assigned2 } }));
      } catch (e) {}
    } catch (e) {
      console.error("Failed to start session", e);
    } finally {
      setIsStarting(false);
    }
  };

  // Show toast when session starts/stops (detect transitions)
  useEffect(() => {
    const prev = prevSessionRef.current;
    const cur = sessionInfo;
    if (!prev && cur) {
      setToast("Service started");
    } else if (prev && !cur) {
      setToast("Service stopped");
    }
    prevSessionRef.current = cur;
  }, [sessionInfo]);

  // auto-hide toast
  useEffect(() => {
    if (!toast) return;
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, [toast]);

  // When pending stop is active, watch for recognized teacher matching the session starter
  useEffect(() => {
    let cancelled = false;
    const tryAutoStop = async () => {
      if (!stopPending || isStopping) return;
      // require session and teacherDetected
      if (!sessionInfo || !sessionInfo.teacher_id) return;
      if (!teacherDetected || teacherDetected.status !== 'success') return;
      // match teacher id (ensure same teacher who started the session)
      if (String(teacherDetected.id) !== String(sessionInfo.teacher_id)) return;

      setIsStopping(true);
      try {
        await axios.post(`${API_BASE}/session/stop`);
        if (cancelled) return;
        // refresh session
        const res = await axios.get(`${API_BASE}/session`);
        setSessionInfo(res.data && res.data.session ? res.data.session : null);
        setToast("Service stopped");
      } catch (e) {
        console.error('Auto-stop failed', e);
        setToast('Failed to stop service');
      } finally {
        setStopPending(false);
        setIsStopping(false);
        try { if (stopTimerRef.current) { clearTimeout(stopTimerRef.current); stopTimerRef.current = null; } } catch(e){}
      }
    };
    tryAutoStop();
    return () => { cancelled = true; };
  }, [stopPending, teacherDetected, sessionInfo, isStopping]);

  return (
    // outer split container: left = camera (85%), right = present students (15%)
    <div className="w-full h-full rounded overflow-hidden flex">
      {/* Left - Camera feed area (85%) */}
      <div className="relative bg-black h-full" style={{ width: '85%' }}>
        <img ref={imgRef} className="w-full h-full object-cover" alt="Camera feed" />

        {/* Toast notification (simple local implementation) */}
        {toast ? (
          <div className="absolute top-6 left-1/2 transform -translate-x-1/2 z-50">
            <div className="bg-black/80 text-white px-4 py-2 rounded-lg shadow">{toast}</div>
          </div>
        ) : null}

        {/* Status overlay - bottom center */}
        <div className="absolute left-1/2 transform -translate-x-1/2 bottom-4 z-40">
          {/* When recognized, make overlay clickable to start service */}
          {overlay.state === 'recognized' ? (
            <button
              onClick={openClassModal}
              className={`inline-flex items-center space-x-3 px-4 py-2 rounded-full bg-white/5 backdrop-blur-sm border ${borderClass} cursor-pointer`}
              style={{ borderWidth: 1 }}
              aria-label="Start service for recognized teacher"
            >
              <span className={`inline-block w-3 h-3 rounded-full ${circleClass}`} aria-hidden="true" />
              <span className={`font-medium ${textClass}`}>{overlay.label} — Start service</span>
            </button>
          ) : overlay.state === 'active' ? (
            <button
              onClick={() => setShowStopConfirm(true)}
              className={`inline-flex items-center space-x-3 px-4 py-2 rounded-full bg-white/5 backdrop-blur-sm border ${borderClass} cursor-pointer`}
              style={{ borderWidth: 1 }}
              aria-label="Service active - stop service"
            >
              <span className={`inline-block w-3 h-3 rounded-full ${circleClass}`} aria-hidden="true" />
              <span className={`font-medium ${textClass}`}>{overlay.label}</span>
            </button>
          ) : overlay.state === 'pending_stop' ? (
            <div className={`inline-flex items-center space-x-3 px-4 py-2 rounded-full bg-white/5 backdrop-blur-sm border ${borderClass}`} style={{ borderWidth: 1 }}>
              <span className={`inline-block w-3 h-3 rounded-full ${circleClass}`} aria-hidden="true" />
              <span className={`font-medium ${textClass}`}>{overlay.label}</span>
            </div>
          ) : overlay.state === 'recognizing' ? (
            <div className={`inline-flex items-center space-x-3 px-4 py-2 rounded-full bg-white/5 backdrop-blur-sm border ${borderClass}`} style={{ borderWidth: 1 }}>
              <span className={`inline-block w-3 h-3 rounded-full ${circleClass}`} aria-hidden="true" />
              <span className={`font-medium ${textClass}`}>{overlay.label}</span>
            </div>
          ) : overlay.state === 'pending_stop' ? (
            <div className={`inline-flex items-center space-x-3 px-4 py-2 rounded-full bg-white/5 backdrop-blur-sm border ${borderClass}`} style={{ borderWidth: 1 }}>
              <span className={`inline-block w-3 h-3 rounded-full ${circleClass}`} aria-hidden="true" />
              <span className={`font-medium ${textClass}`}>{overlay.label}</span>
            </div>
          ) : (
            // default / ready state
            <div>
              {overlay.state === 'ready' && (
                (unrecognizedDetected) ||
                (
                  detectCount > 0 &&
                  // don't show if teacher is matched
                  !(teacherDetected && teacherDetected.status === 'success') &&
                  // don't show if student is matched OR if a student match exists in the DB
                  // (recognize-camera can return status 'service_inactive' when no active class,
                  // but the endpoint also exposes `known` when a face matched a student/teacher record).
                  !(studentDetected && (studentDetected.status === 'success' || studentDetected.known))
                )
              ) ? (
                // Show a prominent unrecognized message similar to the recognized state
                <div className={`inline-flex items-center space-x-3 px-4 py-2 rounded-full bg-yellow-600/90 backdrop-blur-sm border ${borderClass}`} style={{ borderWidth: 1 }}>
                  <span className={`inline-block w-3 h-3 rounded-full bg-white`} aria-hidden="true" />
                  <span className={`font-medium text-white`}>Unidentified face detected</span>
                </div>
              ) : (
                <div className={`inline-flex items-center space-x-3 px-4 py-2 rounded-full bg-white/10 backdrop-blur-sm border ${borderClass}`} style={{ borderWidth: 1 }}>
                  <span className={`inline-block w-3 h-3 rounded-full ${circleClass}`} aria-hidden="true" />
                  <span className={`font-medium ${textClass}`}>{overlay.label}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Keep modals here (they are fixed and will overlay viewport as before) */}
        {showClassModal ? (
          <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => setShowClassModal(false)} />
            <div className="relative bg-gray-800 text-white rounded-lg p-4 w-80 shadow-lg ring-1 ring-black/20 z-10">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <h3 className="text-md font-semibold text-white">Choose class to start</h3>
                  <p className="text-sm text-gray-300 text-left">for {teacherDetected ? teacherDetected.name : "teacher"}</p>
                </div>
              </div>
              <select className="w-full p-2 bg-black-700 text-gray-700 border border-gray-600 rounded mb-3" value={selectedClass} onChange={(e) => setSelectedClass(e.target.value)}>
                {classesList.length === 0 ? (
                  <option value="">No classes</option>
                ) : (
                  classesList.map((c) => (
                    <option key={c.id} value={c.id}>{(c.subjectName || c.name || "Untitled")} — {`${c.gradeLevel || ''} ${c.section || ''}`.trim()}</option>
                  ))
                )}
              </select>

              <div className="flex justify-end space-x-2">
                <button
                  type="button"
                  className="px-3 py-1 text-sm rounded bg-gray-600 text-white hover:bg-gray-700"
                  onClick={() => setShowClassModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className={`px-3 py-1 text-sm rounded ml-2 ${selectedClass && !isStarting ? 'bg-green-600 text-white hover:bg-green-700' : 'bg-gray-600 text-gray-300 opacity-60 cursor-not-allowed'}`}
                  onClick={startService}
                  aria-disabled={!selectedClass || isStarting}
                >{isStarting ? 'Starting...' : 'Confirm'}</button>
              </div>
            </div>
          </div>
        ) : null}
        {/* Stop confirmation modal */}
        {showStopConfirm ? (
          <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/40" onClick={() => setShowStopConfirm(false)} />
            <div className="relative bg-gray-800 text-white rounded-lg p-4 w-80 shadow-lg ring-1 ring-black/20 z-10">
              <h3 className="text-md font-semibold mb-2">Stop service?</h3>
              <p className="text-sm text-gray-300 mb-4">Are you sure you want to stop the active session?</p>
              <div className="flex justify-end space-x-2">
                <button className="px-3 py-1 text-sm rounded bg-gray-600 text-white hover:bg-gray-700" onClick={() => setShowStopConfirm(false)}>Cancel</button>
                <button className="px-3 py-1 text-sm rounded ml-2 bg-red-600 text-white hover:bg-red-700" onClick={async () => {
                  // Instead of stopping immediately, set a pending flag and require teacher re-recognition
                  setShowStopConfirm(false);
                  // start pending stop flow
                  setStopPending(true);
                  setToast("Scan face to stop service");
                  // clear any previous timer
                  try { if (stopTimerRef.current) clearTimeout(stopTimerRef.current); } catch(e){}
                  // timeout pending stop after 30s
                  stopTimerRef.current = setTimeout(() => {
                    setStopPending(false);
                    setToast(null);
                  }, 30000);
                }}>Stop</button>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* Right - Present Students list (15%) */}
      <div className="h-full bg-gray-900 text-white p-3 overflow-y-auto whitespace-nowrap" style={{ width: '15%' }}>
        <div className="sticky top-0">
          <p className="text-xs text-gray-300 mb-3">Currently checked-in</p>
        </div>
        <div>
          {presentStudents && presentStudents.length > 0 ? (
            <ul className="space-y-2">
              {presentStudents.map((s) => (
                <li key={s.id} className="px-2 py-1 bg-gray-800 rounded">
                  <span className="text-sm">{(s.lastname+"," || s.firstname) ? `${(s.lastname+"," || "").trim()} ${(s.firstname || "").trim()}`.trim() : (s.name || s.id)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-sm text-gray-400">No students present</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default CameraFeed;
