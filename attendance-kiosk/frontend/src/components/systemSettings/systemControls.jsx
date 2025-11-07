import React from "react";

function SystemControlsTab() {
  return (
    <div className="animate-fadeIn mt-8">
      <h2 className="text-3xl font-bold mb-6">System Controls</h2>
      <div className="flex flex-wrap gap-8 mt-24 align-center justify-center">
        <button className="bg-red-600 hover:bg-red-700 px-6 py-3 rounded-lg transition">
          Restart Device
        </button>
        <button className="bg-red-700 hover:bg-red-800 px-6 py-3 rounded-lg transition">
          Shutdown
        </button>
      </div>
    </div>
  );
}

export default SystemControlsTab;
