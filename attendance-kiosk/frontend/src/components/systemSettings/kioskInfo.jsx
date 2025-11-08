import React from "react";
import { FaWifi } from "react-icons/fa";

function KioskInfoTab({ deviceInfo, onRefresh }) {
  const serial = deviceInfo?.serial || "Unknown";
  const hostname = deviceInfo?.hostname || deviceInfo?.name || "Unknown";
  const ip = deviceInfo?.ip || deviceInfo?.ipAddress || "Unknown";
  const assignedRoom = deviceInfo?.location || deviceInfo?.assignedRoomName || "Not Assigned";
  const osVersion = deviceInfo?.osVersion || "Unknown";
  const appVersion = deviceInfo?.appVersion || "Unknown";

  return (
    <div className="animate-fadeIn space-y-6 mt-12 text-left">
      <div className="flex justify-between items-start">
        <h2 className="text-3xl font-bold mb-6">Kiosk Information</h2>
        <div className="space-x-2">
          <button
            onClick={onRefresh}
            className="bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded-lg transition text-sm"
          >
            Refresh Rooms
          </button>
        </div>
      </div>

      <div className="space-y-2 text-gray-200">
        <p><strong>Serial Number:</strong> {serial}</p>
        <p><strong>Hostname:</strong> {hostname}</p>
        <p><strong>IP Address:</strong> {ip}</p>
        <p><strong>Assigned Room:</strong> {assignedRoom}</p>
        <p><strong>OS Version:</strong> {osVersion}</p>
        <p><strong>App Version:</strong> {appVersion}</p>
      </div>

      <div className="pt-6 border-t border-gray-700">
        <h3 className="text-xl font-semibold mb-2 flex items-center gap-2">
          <FaWifi /> Network
        </h3>
        <button className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded-lg transition">
          Test Connection
        </button>
      </div>
    </div>
  );
}

export default KioskInfoTab;
