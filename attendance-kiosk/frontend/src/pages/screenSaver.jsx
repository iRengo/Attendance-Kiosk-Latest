import { useState, useEffect } from "react";
import logo from "../assets/images/aics_logo.png";
import bgImage from "../assets/images/bg.jpg";
import RoomInfo from "../components/screenSaver/roomInfo";
import TimeDisplay from "../components/screenSaver/timeDisplay";
import SwipeHint from "../components/screenSaver/swipeHint";
import { useSwipeUp } from "../components/screenSaver/useSwipeup";
import { useNavigate } from "react-router-dom";
import NetworkStatus from "../components/networkStatus"; 
import { FaLock } from "react-icons/fa";
import { useCallback } from "react";

function ScreenSaver() {
  const [time, setTime] = useState(new Date());
  const [swipeUp, setSwipeUp] = useState(false);
  const [locked, setLocked] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // only trigger swipe-up action when not locked
  useSwipeUp(() => {
    if (!locked) setSwipeUp(true);
  });

  useEffect(() => {
    if (swipeUp && !locked) {
      const timer = setTimeout(() => navigate("/landing"), 500);
      return () => clearTimeout(timer);
    }
  }, [swipeUp, navigate, locked]);

  // Poll device info to detect if kiosk has an assigned room. If not assigned, lock UI.
  const fetchDeviceInfo = useCallback(async () => {
    try {
      const res = await fetch("http://localhost:8000/device/info");
      if (!res.ok) {
        // treat as locked when backend returns non-OK
        setLocked(true);
        return;
      }
      const data = await res.json();
      const kiosk = data && data.kiosk ? data.kiosk : null;
      const roomId = kiosk && kiosk.assignedRoomId ? kiosk.assignedRoomId : null;
      setLocked(!roomId);
    } catch (err) {
      // on network or parsing errors, be conservative and lock UI
      setLocked(true);
    }
  }, []);

  useEffect(() => {
    fetchDeviceInfo();
    const id = setInterval(fetchDeviceInfo, 5000);
    return () => clearInterval(id);
  }, [fetchDeviceInfo]);

  return (
    <div
      className={`relative text-white w-full h-full ${locked ? "cursor-not-allowed" : "cursor-pointer"} transition-transform duration-500 overflow-hidden ${
        swipeUp ? "-translate-y-full" : "translate-y-0"
      }`}
      onClick={() => { if (!locked) setSwipeUp(true); }}
    >
      <div
        className="absolute inset-0 -z-10 bg-cover mt-8 bg-center bg-no-repeat opacity-25"
        style={{
          backgroundImage: `url(${bgImage})`,
        }}
      ></div>

      <div className="absolute mt-8 sm:top-6 sm:left-6">
        <NetworkStatus />
      </div>

      <div className="absolute mt-8 right-4 sm:top-6 sm:right-6">
        <img src={logo} alt="Logo" className="w-16 sm:w-24 h-auto opacity-90" />
      </div>

      <div className="absolute top-1/2 left-4 sm:left-6 transform -translate-y-1/2">
        <RoomInfo />
      </div>

      {/* Lock overlay: covers everything and prevents interaction when no room assigned */}
      {locked && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-transparent text-white pointer-events-auto">
          <div className="flex flex-col items-center space-y-4 p-6 bg-gray-500 border border-white/20 rounded-lg">
            <FaLock className="text-4xl text-red-400" />
            <div className="text-2xl font-semibold">Room Unavailable</div>
            <div className="text-sm text-gray-300 max-w-lg text-center">This kiosk is not assigned to a room or the room information is unavailable. Interactions are disabled until the kiosk is assigned. Contact your administrator.</div>
          </div>
        </div>
      )}

      <div className="absolute bottom-4 left-4 sm:bottom-6 sm:left-6">
        <TimeDisplay time={time} />
      </div>
      
      <div className="absolute bottom-4 right-12 sm:bottom-6 sm:right-6">
        <SwipeHint />
      </div>
    </div>
  );
}

export default ScreenSaver;
