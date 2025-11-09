import React from "react";

/**
 * Small toast-style loading indicator that appears at the top-right of the screen.
 * Looks like: [spinner] <message>
 * Props:
 *  - visible: boolean
 *  - message: string (optional)
 */
export default function LoadingOverlay({ visible, message }) {
  if (!visible) return null;

  return (
    <div className="fixed top-4 right-4 z-50">
      <div className="flex items-center gap-3 bg-gray-800 bg-opacity-70 text-white px-3 py-2 rounded-lg shadow-lg backdrop-blur-sm">
        {/* small spinner */}
        <div className="w-5 h-5 rounded-full border-2 border-white border-t-transparent animate-spin" aria-hidden="true" />
        <div className="flex flex-col text-sm leading-tight">
          <span className="font-medium">{message || "Loading..."}</span>
        </div>
      </div>
    </div>
  );
}
