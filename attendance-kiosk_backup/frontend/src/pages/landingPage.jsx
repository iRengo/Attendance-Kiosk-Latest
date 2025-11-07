import React from "react";
import { useNavigate } from "react-router-dom";
import { FaArrowLeft } from "react-icons/fa";

import loginIcon from "../assets/icons/login.png";
import classesIcon from "../assets/icons/class-history.png";
import notifIcon from "../assets/icons/notification.png";
import settingsIcon from "../assets/icons/settings.png";
import NetworkStatus from "../components/networkStatus";
import TimeDateDisplay from "../components/landingPage/timedateDisplay";

function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="relative w-full h-full flex flex-col items-center justify-center px-4 text-white">
      <div className="absolute bottom-4 left-4 sm:bottom-6 sm:left-6">
        <NetworkStatus />
      </div>

      <button
        onClick={() => navigate("/")}
        className="absolute top-6 left-6 flex items-center space-x-2 text-white opacity-80 hover:opacity-100 transition"
      >
        <FaArrowLeft className="text-2xl" />
        <span className="text-lg font-medium">Back</span>
      </button>

      <div className="absolute top-6 right-6">
        <TimeDateDisplay />
      </div>

      <div className="grid grid-cols-2 gap-4 w-full max-w-md sm:max-w-lg md:max-w-2xl">
        <div
          className="flex flex-col items-center justify-center space-y-1 cursor-pointer hover:scale-105 transition-transform bg-gray-700/80 rounded-xl p-4 shadow-md"
          onClick={() => navigate("/systemService")}
        >
          <img
            src={loginIcon}
            alt="Login"
            className="w-16 h-16 object-contain"
          />
          <span className="text-lg font-semibold">Login</span>
        </div>

        <div
          className="flex flex-col items-center justify-center space-y-1 cursor-pointer hover:scale-105 transition-transform bg-gray-700/80 rounded-xl p-4 shadow-md"
          onClick={() => alert("Class history clicked")}
        >
          <img
            src={classesIcon}
            alt="Classes"
            className="w-16 h-16 object-contain"
          />
          <span className="text-lg font-semibold">Class History</span>
        </div>

        <div
          className="flex flex-col items-center justify-center space-y-1 cursor-pointer hover:scale-105 transition-transform bg-gray-700/80 rounded-xl p-4 shadow-md"
          onClick={() => alert("Notifications clicked")}
        >
          <img
            src={notifIcon}
            alt="Notifications"
            className="w-16 h-16 object-contain"
          />
          <span className="text-lg font-semibold">Notifications</span>
        </div>

        <div
          className="flex flex-col items-center justify-center space-y-1 cursor-pointer hover:scale-105 transition-transform bg-gray-700/80 rounded-xl p-4 shadow-md"
          onClick={() => navigate("/settings")}
        >
          <img
            src={settingsIcon}
            alt="Settings"
            className="w-16 h-16 object-contain"
          />
          <span className="text-lg font-semibold">Settings</span>
        </div>
      </div>
    </div>
  );
}

export default LandingPage;
