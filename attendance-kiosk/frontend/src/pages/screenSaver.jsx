import { useState, useEffect } from "react";
import logo from "../assets/images/aics_logo.png";
import bgImage from "../assets/images/bg.jpg";
import RoomInfo from "../components/screenSaver/roomInfo";
import TimeDisplay from "../components/screenSaver/timeDisplay";
import SwipeHint from "../components/screenSaver/swipeHint";
import { useSwipeUp } from "../components/screenSaver/useSwipeup";
import { useNavigate } from "react-router-dom";
import NetworkStatus from "../components/networkStatus"; 

function ScreenSaver() {
  const [time, setTime] = useState(new Date());
  const [swipeUp, setSwipeUp] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useSwipeUp(() => setSwipeUp(true));

  useEffect(() => {
    if (swipeUp) {
      const timer = setTimeout(() => navigate("/landing"), 500);
      return () => clearTimeout(timer);
    }
  }, [swipeUp, navigate]);

  return (
    <div
      className={`relative text-white w-full h-full cursor-pointer transition-transform duration-500 overflow-hidden ${
        swipeUp ? "-translate-y-full" : "translate-y-0"
      }`}
      onClick={() => setSwipeUp(true)}
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
