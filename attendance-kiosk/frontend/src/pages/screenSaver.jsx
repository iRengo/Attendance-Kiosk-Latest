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
  const [locked, setLocked] = useState(false); // locks swipe while unassigned or unregistered
  const [needsRegistration, setNeedsRegistration] = useState(false);
  const [codeInput, setCodeInput] = useState("");
  const [codeStatus, setCodeStatus] = useState(null); // {type:'error'|'success', message:''}
  const [submitting, setSubmitting] = useState(false);
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
        setLocked(true);
        return;
      }
      const data = await res.json();
      const kiosk = data && data.kiosk ? data.kiosk : null;
      const roomId = kiosk && kiosk.assignedRoomId ? kiosk.assignedRoomId : null;
      const nr = data && typeof data.needsRegistration === 'boolean' ? data.needsRegistration : (!kiosk);
      setNeedsRegistration(nr);
      // locked if registration required OR no room assignment yet
      setLocked(nr || !roomId);
    } catch (err) {
      setLocked(true);
      setNeedsRegistration(false);
    }
  }, []);

  const submitRegistrationCode = async (e) => {
    e.preventDefault();
    if (!codeInput.trim()) {
      setCodeStatus({ type: 'error', message: 'Enter a code.' });
      return;
    }
    setSubmitting(true);
    setCodeStatus(null);
    try {
      const res = await fetch("http://localhost:8000/device/register/code", {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: codeInput.trim() })
      });
      const data = await res.json();
      if (!res.ok) {
        let msg = data && data.error ? data.error : 'registration_failed';
        if (msg === 'invalid_code') msg = 'Code is invalid.';
        else if (msg === 'code_used') msg = 'Code already used.';
        else if (msg === 'code_expired') msg = 'Code expired.';
        else if (msg === 'firestore_unavailable') msg = 'Service unavailable.';
        else if (msg === 'already_registered') msg = 'Already registered.';
        setCodeStatus({ type: 'error', message: msg });
      } else {
        setCodeStatus({ type: 'success', message: 'Kiosk registered successfully!' });
        setNeedsRegistration(false);
        setTimeout(() => {
          fetchDeviceInfo();
        }, 750);
      }
    } catch (err) {
      setCodeStatus({ type: 'error', message: 'Network error.' });
    } finally {
      setSubmitting(false);
    }
  };

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

      {/* Registration modal */}
      {needsRegistration && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/70 backdrop-blur-lg mt-6 text-white pointer-events-auto">
          <form onSubmit={submitRegistrationCode} className="flex flex-col w-full max-w-md space-y-4 p-6 bg-slate-700/100 border border-white/20 rounded-lg">
            <div className="flex items-center space-x-3">
              <h2 className="text-xl font-semibold">Kiosk Registration Required</h2>
            </div>
            <p className="text-sm text-gray-200">Enter the one-time admin code to register this kiosk. Contact your administrator if you do not have a code.</p>
            <input
              type="text"
              value={codeInput}
              onChange={(e) => setCodeInput(e.target.value.toUpperCase())}
              placeholder="ADMIN CODE"
              className="px-3 py-2 rounded bg-slate-800 border border-slate-500 focus:outline-none focus:ring focus:ring-blue-400 tracking-widest uppercase text-center"
              disabled={submitting}
              autoFocus
            />
            {codeStatus && (
              <div className={`text-sm ${codeStatus.type === 'error' ? 'text-red-400' : 'text-green-300'}`}>{codeStatus.message}</div>
            )}
            <div className="flex items-center justify-between">
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 font-medium"
              >
                {submitting ? 'Registering...' : 'Register'}
              </button>
              <button
                type="button"
                onClick={fetchDeviceInfo}
                disabled={submitting}
                className="text-sm underline decoration-dotted hover:text-blue-300"
              >
                Retry Info
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Lock overlay for room assignment (only show if locked and not needsRegistration) */}
      {locked && !needsRegistration && (
        <div className="fixed inset-0 z-40 flex flex-col items-center justify-center bg-transparent text-white pointer-events-auto">
          <div className="flex flex-col items-center space-y-4 p-6 bg-gray-500/90 border border-white/20 rounded-lg">
            <FaLock className="text-4xl text-red-400" />
            <div className="text-2xl font-semibold">Room Unavailable</div>
            <div className="text-sm text-gray-200 max-w-lg text-center">This kiosk has no room assigned yet. Once assigned remotely, interaction will unlock automatically.</div>
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
