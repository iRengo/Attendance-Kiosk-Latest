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
  const stopTimerRef = useRef(null);
  const prevSessionRef = useRef(null);
  const [toast, setToast] = useState(null);
  const toastTimerRef = useRef(null);

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

  // derive overlay state
  let overlay = { state: "ready", label: "Ready to Scan Teacher Face" };
  if (stopPending) {
    overlay = { state: "pending_stop", label: "Scan face to stop service" };
  } else if (sessionInfo && sessionInfo.class_id) {
    overlay = { state: "active", label: "Active" };
  } else if (teacherDetected) {
    overlay = { state: "recognized", label: teacherDetected.name || "Teacher" };
  }

  const circleClass = {
    ready: "bg-white",
    recognized: "bg-yellow-400",
    active: "bg-red-500",
    pending_stop: "bg-blue-400",
  }[overlay.state];

  const textClass = {
    ready: "text-white",
    recognized: "text-yellow-400",
    active: "text-green-400",
    pending_stop: "text-blue-400",
  }[overlay.state];

  const borderClass = {
    ready: "border-white",
    recognized: "border-yellow-400",
    active: "border-green-400",
    pending_stop: "border-blue-400",
  }[overlay.state];

  const openClassModal = async () => {
    if (!teacherDetected) return;
    try {
      const res = await axios.get(`${API_BASE}/session/classes?teacher_id=${encodeURIComponent(teacherDetected.id)}`);
      const cls = (res.data && res.data.classes) || [];
      setClassesList(cls);
      setSelectedClass(cls.length > 0 ? cls[0].id : "");
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
    <div className="relative w-full h-full bg-black rounded overflow-hidden">
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
        ) : (
          <div className={`inline-flex items-center space-x-3 px-4 py-2 rounded-full bg-white/10 backdrop-blur-sm border ${borderClass}`} style={{ borderWidth: 1 }}>
            <span className={`inline-block w-3 h-3 rounded-full ${circleClass}`} aria-hidden="true" />
            <span className={`font-medium ${textClass}`}>{overlay.label}</span>
          </div>
        )}
      </div>

      

  
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
  );
}

export default CameraFeed;
