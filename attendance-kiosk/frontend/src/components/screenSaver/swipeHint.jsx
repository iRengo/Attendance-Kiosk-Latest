import React from "react";
import { FaChevronUp } from "react-icons/fa";

function SwipeHint({ text = "Tap the screen." }) {
  return (
    <div className="flex items-center space-x-2 mb-5 mr-10 text-gray-300 animate-pulse">
      <span className="text-md sm:text-md md:text-md">{text}</span>
      
    </div>
  );
}

export default SwipeHint;
