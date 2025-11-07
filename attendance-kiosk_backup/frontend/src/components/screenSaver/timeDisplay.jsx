import React from "react";

function TimeDisplay({ time }) {
  const formattedTime = time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const formattedDate = time.toLocaleDateString([], {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  return (
    <div className="flex flex-col space-y-1 text-left">
      <span className="text-3xl sm:text-4xl md:text-5xl font-semibold">{formattedTime}</span>
      <span className="text-lg sm:text-xl md:text-2xl text-gray-300">{formattedDate}</span>
    </div>
  );
}

export default TimeDisplay;
