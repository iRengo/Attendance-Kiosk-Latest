import React, { useState, useEffect } from "react";

function TimeDateDisplay() {
    const [currentTime, setCurrentTime] = useState("");
    const [currentDate, setCurrentDate] = useState("");
    const [currentDay, setCurrentDay] = useState("");

    useEffect(() => {
        const updateTime = () => {
            const now = new Date();
            const time = now.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
            });
            const date = now.toLocaleDateString([], {
                month: "short",
                day: "numeric",
                year: "numeric",
            });
            const day = now.toLocaleDateString([], { weekday: "long" });

            setCurrentTime(time);
            setCurrentDate(date);
            setCurrentDay(day);
        };

        updateTime();
        const interval = setInterval(updateTime, 1000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="flex flex-col items-end text-gray-200 text-sm">
            
            <span className="font-semibold text-2xl">{currentTime}</span>

            <div className="flex space-x-2">
                <span className="text-white">{currentDay},</span>
                <span>{currentDate}</span>
            </div>
        </div>

    );
}

export default TimeDateDisplay;
