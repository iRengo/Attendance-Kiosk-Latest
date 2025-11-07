import React from "react";
import { FaWifi, FaDatabase, FaSyncAlt } from "react-icons/fa";

function KioskInfoTab({ deviceInfo }) {
  return (
    <div className="animate-fadeIn space-y-6 mt-12 text-left">
      <h2 className="text-3xl font-bold mb-6">Kiosk Information</h2>
      <div className="space-y-2 text-gray-200">
        <p><strong>Serial Number:</strong> {deviceInfo.serial}</p>
        <p><strong>Hostname:</strong> {deviceInfo.hostname}</p>
        <p><strong>IP Address:</strong> {deviceInfo.ip}</p>
        <p><strong>Assigned Room:</strong> {deviceInfo.location}</p>
        <p><strong>OS Version:</strong> {deviceInfo.osVersion}</p>
        <p><strong>App Version:</strong> {deviceInfo.appVersion}</p>
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
