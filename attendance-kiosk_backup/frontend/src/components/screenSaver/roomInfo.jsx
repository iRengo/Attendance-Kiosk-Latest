import React from "react";
import { FaCircle } from "react-icons/fa";

function RoomInfo({ room = "ROOM 103", status = "Available", statusColor = "green-300" }) {
  return (
    <div className="flex flex-col space-y-2 sm:space-y-3 max-w-lg overflow-hidden">
      <p
        className="text-6xl sm:text-8xl md:text-8xl lg:text-12xl font-bold leading-tight"
        style={{
          animation: "float 6s ease-in-out infinite",
        }}
      >
        {room}
      </p>
       <div className="flex items-center space-x-2 sm:space-x-3">
        <FaCircle className="text-green-500 text-sm sm:text-base animate-pulse" />
        <span className="text-md sm:text-xl md:text-2xl font-small text-green-500">{status}</span>
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
