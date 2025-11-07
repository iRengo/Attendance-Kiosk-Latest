import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

// Base URL for backend API. Allow overriding with Vite env var VITE_API_BASE
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function TopInfo({ teacherName: propTeacherName = "", title = "Teacher", classNameText: propClassName = "" }) {
  const [sessionInfo, setSessionInfo] = useState(null);
  const [teacherDetected, setTeacherDetected] = useState(null);
  const lastTeacherRef = React.useRef(null);

  // Poll current session to display active class when started
  useEffect(() => {
    let mounted = true;
    const fetchSession = async () => {
      try {
        const res = await fetch(`${API_BASE}/session`);
        if (!res.ok) return;
        const json = await res.json();
        if (!mounted) return;
        setSessionInfo(json.session || null);
      } catch (e) {
        // ignore
      }
    };
    fetchSession();
    const id = setInterval(fetchSession, 3000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  // Poll for teacher recognition (low rate). When a teacher is recognized show their downloaded local photo.
  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/recognize-teacher`);
        if (!res.ok) return;
        const json = await res.json();
        if (!mounted) return;
        // Persist last recognized teacher until a different id appears.
        if (json && json.status === 'success' && json.id) {
          // update if new id
          if (!lastTeacherRef.current || String(lastTeacherRef.current.id) !== String(json.id)) {
            lastTeacherRef.current = json;
            setTeacherDetected(json);
          } else {
            // same id, ensure displayed
            setTeacherDetected(lastTeacherRef.current);
          }
        } else {
          // if there's no active session, clear immediately
          if (!(sessionInfo && sessionInfo.class_id)) {
            lastTeacherRef.current = null;
            setTeacherDetected(null);
          }
        }
      } catch (e) {
        // ignore
      }
    };
    poll();
    const id = setInterval(poll, 1000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  // Only show teacher name and subject when a session is active and class is chosen
  const isActive = sessionInfo && sessionInfo.class_id;
  const teacherName = isActive ? (sessionInfo.teacher_name || propTeacherName) : "";
  const classNameText = isActive ? (sessionInfo.class_name || propClassName) : "";
  const titleText = isActive ? "Active" : "Service inactive";

  // Clear recognized teacher immediately when session ends
  useEffect(() => {
    if (!isActive) {
      lastTeacherRef.current = null;
      setTeacherDetected(null);
    }
  }, [isActive]);

  const navigate = useNavigate();

  return (
    <div className="flex justify-between items-start mb-4">
      <div className="flex items-center space-x-4">
        <div className="w-16 h-16 rounded-full overflow-hidden bg-gray-700 flex items-center justify-center">
          {/**
           * teacher image precedence:
           * 1. session.profilePicUrl or session.teacher_profilePicUrl (if provided by backend)
           * 2. fallback to local photos path: /photos/teachers/{teacherId}.jpg
           */}
          {(() => {
            // Only show a teacher image while a session is active.
            // If a session is active prefer session profilePicUrl then session teacher_id.
            // When no active session, always show the default SVG (teacherImgSrc = null).
            const sessionProfile = isActive ? (sessionInfo.profilePicUrl || sessionInfo.teacher_profilePicUrl || '') : '';
            const teacherId = isActive ? (sessionInfo.teacher_id || (teacherDetected ? (teacherDetected.id || '') : '')) : '';
            const teacherImgSrc = isActive
              ? (sessionProfile
                  ? (sessionProfile.startsWith('/') ? `${API_BASE}${sessionProfile}` : sessionProfile)
                  : (teacherId ? `${API_BASE}/photos/teachers/${teacherId}.jpg` : null))
              : null;
            return teacherImgSrc ? (
              <img
                src={teacherImgSrc}
                alt={teacherName || 'teacher'}
                className="w-full h-full object-cover"
                onError={(e) => { e.currentTarget.onerror = null; e.currentTarget.style.display = 'none'; }}
              />
            ) : (
              <svg className="w-8 h-8 text-gray-400" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4z" fill="currentColor" />
                <path d="M4 20c0-2.21 3.58-4 8-4s8 1.79 8 4v1H4v-1z" fill="currentColor" />
              </svg>
            );
          })()}
        </div>
        <div>
          <p className="font-bold text-xl">{isActive ? teacherName : ""}</p>
          <p className={`mt-1 text-left ${isActive ? 'text-green-300' : 'text-gray-400'}`}>{titleText}</p>
        </div>
      </div>

      <div className="text-right">
        <p className="font-bold text-xl">{isActive ? classNameText : ""}</p>
        {/* Disable Return navigation while a session is active */}
        <p
          className={`text-sm text-gray-300 mt-1 ${isActive ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer hover:text-gray-100'}`}
          onClick={() => { if (!isActive) navigate('/landing'); }}
          aria-disabled={isActive}
        >Return</p>
      </div>
    </div>
  );
}

export default TopInfo;
