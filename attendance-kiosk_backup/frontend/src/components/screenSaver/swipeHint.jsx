import React from "react";
import { FaChevronUp } from "react-icons/fa";

function SwipeHint({ text = "Swipe up to login" }) {
  return (
    <div className="flex items-center space-x-2 mb-5 mr-10 text-gray-300 animate-pulse">
      <span className="text-lg sm:text-xl md:text-2xl">{text}</span>
      
    </div>
  );
}

export default SwipeHint;
