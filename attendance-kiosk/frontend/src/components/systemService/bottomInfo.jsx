import React, { useState, useEffect } from "react";
import axios from "axios";

// Base URL for backend API. Allow overriding with Vite env var VITE_API_BASE
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function BottomInfo({ studentCount = "N/A" }) {
  const [studentName, setStudentName] = useState("Not Available");
  const [studentStatus, setStudentStatus] = useState("Service inactive");
  const [sessionInfo, setSessionInfo] = useState(null);
  const [studentId, setStudentId] = useState(null);
  const [studentProfileUrl, setStudentProfileUrl] = useState(null);
  const lastStudentRef = React.useRef(null);
  const [presentCount, setPresentCount] = useState(0);
  const [time, setTime] = useState(new Date());
  const [unrecognized, setUnrecognized] = useState(false);
  const [teacherDetected, setTeacherDetected] = useState(null);
  // recognition stability refs (require ~1.5s hold-still before declaring unrecognized)
  const recognitionStartRef = React.useRef(null);
  const recognitionClearTimerRef = React.useRef(null);
  // throttle marking attendance per-student (avoid spamming)
  const lastMarkedRef = React.useRef(new Map());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    // Only run recognition polling when a session is active. When no session is active,
    // BottomInfo should show the default "Not Available / Service inactive" values.
    let mounted = true;

    if (!(sessionInfo && sessionInfo.class_id)) {
      // No active session: reset UI and do not poll recognize-camera
      lastStudentRef.current = null;
      setStudentName('Not Available');
      setStudentStatus('Service inactive');
      setStudentId(null);
      setStudentProfileUrl(null);
      setUnrecognized(false);
      // clear any pending timers
      try { if (recognitionClearTimerRef.current) { clearTimeout(recognitionClearTimerRef.current); recognitionClearTimerRef.current = null; } } catch (e) {}
      recognitionStartRef.current = null;
      return () => { mounted = false; };
    }

    // Session is active: poll multi-face endpoint and apply existing behavior + stability logic.
    const poll = async () => {
      if (!mounted) return;
      try {
        const res = await axios.get(`${API_BASE}/recognize-students`);
        const data = res.data || {};
        const results = Array.isArray(data.results) ? data.results : [];
        const detected = (typeof data.detected !== 'undefined') ? Number(data.detected) : (results.length || 0);

        // session active but no recognized student yet: show detecting
        if (!lastStudentRef.current) {
          setStudentName('Detecting faces...');
          setStudentStatus('Detecting faces...');
        }

        // Choose a primary student for display: first success, otherwise first denied, otherwise first unknown
        const primary = results.find(r => r && r.status === 'success')
          || results.find(r => r && r.status === 'denied')
          || (results.length ? results[0] : null);

        if (primary && (primary.id || primary.status)) {
          if (!lastStudentRef.current || String(lastStudentRef.current.id) !== String(primary.id) || lastStudentRef.current.status !== primary.status) {
            lastStudentRef.current = primary;
            const isDenied = primary.status === 'denied' || primary.registered === false;
            setStudentName(primary.name || (isDenied ? 'Unknown' : 'Unknown'));
            if (isDenied) {
              setStudentStatus('Denied - Not registered');
              setStudentId(primary.id || null);
              setStudentProfileUrl(null);
            } else if (primary.status === 'success') {
              setStudentStatus('Present');
              setStudentId(primary.id || null);
              setStudentProfileUrl(primary.profilePicUrl ? (String(primary.profilePicUrl).startsWith('/') ? `${API_BASE}${primary.profilePicUrl}` : primary.profilePicUrl) : (primary.id ? `${API_BASE}/photos/students/${primary.id}.jpg` : null));
            } else {
              // unknown or other statuses
              setStudentStatus('Detecting faces...');
              setStudentId(null);
              setStudentProfileUrl(null);
            }
          }
        }

        // Mark attendance for all successes (throttled per-student)
        if (sessionInfo && sessionInfo.class_id && results.length) {
          const now = Date.now();
          for (const r of results) {
            if (r && r.status === 'success' && r.id) {
              const lastTs = lastMarkedRef.current.get(String(r.id)) || 0;
              if (now - lastTs > 2000) { // throttle 2s per student
                try {
                  const m = await axios.post(`${API_BASE}/session/mark`, { student_id: r.id, student_name: r.name });
                  lastMarkedRef.current.set(String(r.id), Date.now());
                  if (m.data && Array.isArray(m.data.studentsPresent)) {
                    setPresentCount(m.data.studentsPresent.length);
                  }
                } catch (e) {
                  // ignore mark errors
                }
              }
            }
          }
        }

        // Handle unrecognized: require continuous detection for ~1.5s before showing.
        try {
          // Only let a teacher match block unrecognized in the pre-session state.
          const teacherBlocks = teacherDetected && teacherDetected.status === 'success' && !(sessionInfo && sessionInfo.class_id);
          const anySuccess = results.some(r => r && r.status === 'success');
          const anyUnknown = results.some(r => r && r.status === 'unknown');
          if (!anySuccess && anyUnknown && detected > 0 && !teacherBlocks) {
            if (!recognitionStartRef.current) {
              recognitionStartRef.current = Date.now();
            } else {
              const elapsed = Date.now() - recognitionStartRef.current;
              if (elapsed >= 1500) {
                setUnrecognized(true);
                // show default avatar when an unidentified face is detected
                setStudentProfileUrl(null);
                // keep the unrecognized flag until detection goes away (detect==0) or status changes
                recognitionStartRef.current = null;
              }
            }
          } else {
            recognitionStartRef.current = null;
            // Clear unrecognized when there is no active unknown detection or no faces present
            if (!(!anySuccess && anyUnknown && detected > 0)) {
              setUnrecognized(false);
            }
          }
        } catch (e) {
          recognitionStartRef.current = null;
        }

      } catch (err) {
        console.error(err);
      }
    };

    const id = setInterval(poll, 100);
    // run immediately once
    poll();

    return () => {
      mounted = false;
      clearInterval(id);
      try { if (recognitionClearTimerRef.current) clearTimeout(recognitionClearTimerRef.current); } catch (e) {}
    };
  }, [sessionInfo, teacherDetected]);

  // Poll recognize-teacher at a low rate so BottomInfo can know if a teacher was matched
  useEffect(() => {
    let mounted = true;
    const fetchTeacher = async () => {
      try {
        const res = await axios.get(`${API_BASE}/recognize-teacher`);
        if (!mounted) return;
        setTeacherDetected(res.data || null);
      } catch (e) {
        if (mounted) setTeacherDetected(null);
      }
    };
    fetchTeacher();
    const tid = setInterval(fetchTeacher, 1500);
    return () => { mounted = false; clearInterval(tid); };
  }, []);

  // Clear persisted student when session ends immediately
  useEffect(() => {
    if (!(sessionInfo && sessionInfo.class_id)) {
      lastStudentRef.current = null;
      setStudentName("Not Available");
      setStudentStatus("Service inactive");
      setStudentId(null);
      setStudentProfileUrl(null);
    }
  }, [sessionInfo]);

  // derive display fields (show unrecognized state when session active)
  const displayName = (sessionInfo && sessionInfo.class_id && unrecognized) ? 'Unidentified face detected' : studentName;
  const displayStatus = (sessionInfo && sessionInfo.class_id && unrecognized) ? 'Unidentified' : studentStatus;

  // Poll for recognized teacher (low rate)
  // Note: start/stop flow moved into CameraFeed overlay. BottomInfo no longer polls for teacher detection.

  // Poll current session (to reflect started state)
  useEffect(() => {
    let mounted = true;
    const fetchSession = async () => {
      try {
        const res = await axios.get(`${API_BASE}/session`);
        if (!mounted) return;
        setSessionInfo(res.data && res.data.session ? res.data.session : null);
        // if session active, fetch attendance counts
        try {
          if (res.data && res.data.session && res.data.session.class_id) {
            const att = await axios.get(`${API_BASE}/session/attendance`);
            const data = att.data || {};
            const present = Array.isArray(data.studentsPresent) ? data.studentsPresent.length : 0;
            setPresentCount(present);
          } else {
            setPresentCount(0);
          }
        } catch (e) {
          // ignore attendance fetch errors
        }
      } catch (e) {
        // ignore
      }
    };
    fetchSession();
    const id = setInterval(fetchSession, 3000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="relative flex justify-between items-center w-full">
      <div className="flex items-center space-x-4 mt-4">
        <div className="w-12 h-12 rounded-full overflow-hidden bg-gray-700 flex items-center justify-center">
          {studentProfileUrl ? (
            <img
              src={studentProfileUrl}
              alt={studentName || 'student'}
              className="w-full h-full object-cover"
              onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.style.display = 'none'; }}
            />
          ) : (
            <svg className="w-6 h-6 text-gray-400" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4z" fill="currentColor" />
              <path d="M4 20c0-2.21 3.58-4 8-4s8 1.79 8 4v1H4v-1z" fill="currentColor" />
            </svg>
          )}
        </div>
        <div>
          <p className="font-bold text-left">{displayName}</p>
          <p className="text-left text-gray-400">{displayStatus}</p>
        </div>
      </div>
      <div className="flex justify-center ml-25">
        {/* Start/Stop controls moved to camera overlay. */}
      </div>

      {/* Start/stop modal and controls moved into CameraFeed overlay; removed from BottomInfo */}
      <div className="text-right">
        <p className="font-bold">Student Present: {sessionInfo && sessionInfo.class_id ? presentCount : studentCount}</p>
        <p className="text-gray-400">
          {time.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" })}{" "}
          {time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </p>
      </div>
    </div>
  );
}

export default BottomInfo;
