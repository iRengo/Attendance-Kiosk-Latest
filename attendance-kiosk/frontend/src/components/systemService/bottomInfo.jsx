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

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    // Poll only when a session is active (sessionInfo.class_id present). Otherwise show Not Available.
    let mounted = true;
    const poll = async () => {
      if (!mounted) return;
      if (!(sessionInfo && sessionInfo.class_id)) {
        // no active session: show Not Available
        setStudentName("Not Available");
        setStudentStatus("Service inactive");
        return;
      } else {
        // session active but no recognized student yet: show detecting
        if (!lastStudentRef.current) {
          setStudentName("Detecting faces...");
          setStudentStatus("Detecting faces...");
        }
      }

      try {
        const res = await axios.get(`${API_BASE}/recognize-camera`);
        const data = res.data || {};
        // Persist last recognized student until a different student is recognized. Clear on session end.
        if (data && data.id && (data.status === "success" || data.status === "denied")) {
          // new detection or changed id
          if (!lastStudentRef.current || String(lastStudentRef.current.id) !== String(data.id) || lastStudentRef.current.status !== data.status) {
            lastStudentRef.current = data;
            // If recognition reports denied or not registered, show denied state
            const isDenied = data.status === "denied" || data.registered === false;
            setStudentName(data.name || (isDenied ? "Unknown" : "Unknown"));
            if (isDenied) {
              setStudentStatus("Denied - Not registered");
              setStudentId(data.id || null);
              // Keep the default avatar when the student is denied / not registered
              // (do not set a profile URL so the SVG placeholder remains visible)
              setStudentProfileUrl(null);
            } else {
              // successful and registered
              setStudentStatus("Present");
              setStudentId(data.id || null);
              setStudentProfileUrl(data.profilePicUrl ? (data.profilePicUrl.startsWith('/') ? `${API_BASE}${data.profilePicUrl}` : data.profilePicUrl) : (data.id ? `${API_BASE}/photos/students/${data.id}.jpg` : null));
              // mark student present on server (idempotent on backend)
              try {
                const m = await axios.post(`${API_BASE}/session/mark`, { student_id: data.id, student_name: data.name });
                if (m.data && Array.isArray(m.data.studentsPresent)) {
                  setPresentCount(m.data.studentsPresent.length);
                }
              } catch (e) {
                // ignore mark errors
              }
            }
          }
        } else {
          // no valid detection this tick: keep showing detecting while session active
          if (sessionInfo && sessionInfo.class_id) {
            if (!lastStudentRef.current) {
              setStudentName("Detecting faces...");
              setStudentStatus("Detecting faces...");
            }
          }
        }
      } catch (err) {
        console.error(err);
      }
    };

    // use a repeating interval while mounted; interval function checks session state each tick
    const id = setInterval(poll, 100); // ~10 FPS when active
    // run immediately once
    poll();

    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [sessionInfo]);

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
          <p className="font-bold text-left">{studentName}</p>
          <p className="text-left text-gray-400">{studentStatus}</p>
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
