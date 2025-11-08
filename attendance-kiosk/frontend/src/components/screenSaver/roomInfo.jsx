import React, { useEffect, useState, useCallback } from "react";
import { FaCircle } from "react-icons/fa";

// Use Vite-configurable API base
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function RoomInfo({ room = "Unavailable" }) {
  const [assignedRoomId, setAssignedRoomId] = useState(null);
  const [statusText, setStatusText] = useState("Unavailable");
  const [statusColorClass, setStatusColorClass] = useState("text-yellow-500");

  const fetchAssignedRoom = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/device/info`);
      if (!res.ok) {
        throw new Error("failed to fetch device info");
      }
      const data = await res.json();
      // accept multiple shapes: { kiosk: { ... } }, { device: { ... } }, or root object
      const kiosk = (data && (data.kiosk || data.device)) || data || null;

      let roomId = null;
      if (kiosk) {
        if (kiosk.assignedRoomId !== undefined && kiosk.assignedRoomId !== null) roomId = kiosk.assignedRoomId;
        if (!roomId && kiosk.assignedRoom !== undefined && kiosk.assignedRoom !== null) roomId = kiosk.assignedRoom;
        if (!roomId && kiosk.assignedRoomName) roomId = kiosk.assignedRoomName;
        if (!roomId && kiosk.roomId !== undefined && kiosk.roomId !== null) roomId = kiosk.roomId;
      }

      // normalize stringy nulls
      if (typeof roomId === 'string') {
        const t = roomId.trim();
        if (t === '' || t.toLowerCase() === 'null' || t.toLowerCase() === 'none') roomId = null;
        else roomId = t;
      }

      if (roomId !== null && roomId !== undefined) {
        setAssignedRoomId(String(roomId));
        setStatusText("Available");
        setStatusColorClass("text-green-500");
      } else {
        setAssignedRoomId(null);
        setStatusText("Unavailable");
        setStatusColorClass("text-yellow-500");
      }
    } catch (err) {
      setAssignedRoomId(null);
      setStatusText("Unavailable");
      setStatusColorClass("text-yellow-500");
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    if (mounted) fetchAssignedRoom();
    const id = setInterval(fetchAssignedRoom, 5000);

    // listen for explicit updates (e.g., camera modal verified kiosk)
    const handler = (ev) => {
      // if the event carries detail.assignedRoomId we can set immediately for snappy UI
      try {
        if (ev && ev.detail && ev.detail.assignedRoomId !== undefined) {
          const v = ev.detail.assignedRoomId;
          if (v !== null && v !== undefined) {
            setAssignedRoomId(String(v));
            setStatusText("Available");
            setStatusColorClass("text-green-500");
            return;
          }
        }
      } catch (e) {}
      // fallback: re-fetch from backend
      fetchAssignedRoom();
    };
    window.addEventListener('kioskAssignedUpdated', handler);

    return () => {
      mounted = false;
      clearInterval(id);
      window.removeEventListener('kioskAssignedUpdated', handler);
    };
  }, [fetchAssignedRoom]);

  const displayRoom = assignedRoomId || room;

  return (
    <div className="flex flex-col space-y-2 sm:space-y-3 max-w-lg overflow-hidden">
      <p
        className="text-6xl sm:text-8xl md:text-8xl lg:text-12xl font-bold leading-tight"
        style={{
          animation: "float 6s ease-in-out infinite",
        }}
      >
        {displayRoom}
      </p>
      <div className="flex items-center space-x-2 sm:space-x-3">
        <FaCircle className={`${statusColorClass} text-sm sm:text-base animate-pulse`} />
        <span className={`text-md sm:text-xl md:text-2xl font-small ${statusColorClass}`}>{statusText}</span>
      </div>
      <style>
        {`
          @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
          }
        `}
      </style>
    </div>
  );
}

export default RoomInfo;
