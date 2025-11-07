import React, { useState } from "react";
import axios from "axios";
import { FaSyncAlt, FaDatabase } from "react-icons/fa";

function DatabaseManagementTab() {
  const [pendingRecords, setPendingRecords] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [lastMessage, setLastMessage] = useState("");

  const handleSync = async () => {
    setSyncing(true);
    setLastMessage("Syncing, please wait...");

    try {
      const res = await axios.get("http://localhost:8000/sync");
      const message = res.data.message || "Sync completed";

      // If backend returns a count, extract it (you can modify your backend to return it)
      const countMatch = message.match(/\d+/);
      const count = countMatch ? parseInt(countMatch[0], 10) : 0;

      setPendingRecords(count);
      setLastMessage(
        count > 0
          ? `✅ ${count} records synced successfully.`
          : "No new records to sync."
      );
    } catch (err) {
      console.error(err);
      setLastMessage("❌ Sync failed: " + err.message);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="animate-fadeIn mt-8 text-white">
      <h2 className="text-3xl font-bold mb-6 text-left">Database Management</h2>

      <div className="grid grid-cols-2 gap-8 bg-gray-800 rounded-2xl p-8 shadow-lg h-[420px]">
        {/* Left Panel */}
        <div className="flex flex-col justify-start text-left space-y-6">
          <h3 className="text-md font-semibold mb-6 flex items-center gap-2">
            <FaDatabase /> Database Actions
          </h3>

          <div className="space-y-3">
            <button
              onClick={handleSync}
              disabled={syncing}
              className={`px-4 py-2 rounded-lg transition flex items-center gap-2 w-fit ${
                syncing ? "bg-gray-500 cursor-not-allowed" : "bg-gray-700 hover:bg-gray-600"
              }`}
            >
              <FaSyncAlt className={`text-lg ${syncing ? "animate-spin" : ""}`} />
              <span>{syncing ? "Syncing..." : "Sync Now"}</span>
            </button>
          </div>
        </div>

        {/* Right Panel (Status Display) */}
        <div className="bg-gray-900 rounded-xl p-6 flex flex-col border border-gray-700">
          <h3 className="text-2xl font-semibold mb-4 text-left">Database Status</h3>
          <div className="space-y-3 text-gray-300 text-left">
            {pendingRecords !== null && (
              <p>
                <strong>Pending Records to Sync:</strong>{" "}
                <span
                  className={
                    pendingRecords > 0 ? "text-yellow-400" : "text-green-400"
                  }
                >
                  {pendingRecords > 0
                    ? pendingRecords
                    : "No pending records. Everything is up to date!"}
                </span>
              </p>
            )}
            {lastMessage && (
              <p className="text-sm text-gray-400 mt-2">{lastMessage}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default DatabaseManagementTab;
