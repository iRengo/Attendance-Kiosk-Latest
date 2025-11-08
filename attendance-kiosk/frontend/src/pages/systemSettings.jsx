import React, { useState, useEffect } from "react";
import { FaArrowLeft } from "react-icons/fa";
import { useNavigate } from "react-router-dom";

import KioskInfoTab from "../components/systemSettings/kioskInfo";
import BetaTestTab from "../components/systemSettings/betaTest";
import SystemControlsTab from "../components/systemSettings/systemControls";
import DatabaseManagementTab from "../components/systemSettings/databaseManagement";

function SettingsPage() {
    const navigate = useNavigate();
    const [activeTab, setActiveTab] = useState("kiosk");

    const [deviceInfo, setDeviceInfo] = useState(null);
    const [loadingInfo, setLoadingInfo] = useState(true);

    useEffect(() => {
        const fetchInfo = async () => {
            setLoadingInfo(true);
            try {
                const res = await fetch("http://localhost:8000/device/info");
                const data = await res.json();
                const kiosk = data && data.kiosk ? data.kiosk : null;
                // normalize to previous deviceInfo shape expected by KioskInfoTab
                if (kiosk) {
                    setDeviceInfo({
                        serial: kiosk.serialNumber || "",
                        hostname: kiosk.name || kiosk.id || window.location.hostname,
                        ip: kiosk.ipAddress || "",
                        location: kiosk.assignedRoomName || "Not Assigned",
                        osVersion: "Raspberry Pi OS (64-bit)",
                        appVersion: "v1.0.0",
                        // pass through raw kiosk fields too
                        ...kiosk,
                    });
                } else {
                    setDeviceInfo(null);
                }
            } catch (err) {
                console.error("Failed to fetch device info", err);
                setDeviceInfo(null);
            } finally {
                setLoadingInfo(false);
            }
        };
        fetchInfo();
    }, []);

    const refreshRooms = async () => {
        try {
            // trigger backend sync (manual)
            await fetch("http://localhost:8000/sync");
        } catch (err) {
            console.error("Sync failed", err);
        }
        // re-fetch device info after sync
        try {
            const res = await fetch("http://localhost:8000/device/info");
            const data = await res.json();
            const kiosk = data && data.kiosk ? data.kiosk : null;
            if (kiosk) {
                setDeviceInfo({
                    serial: kiosk.serialNumber || "",
                    hostname: kiosk.name || kiosk.id || window.location.hostname,
                    ip: kiosk.ipAddress || "",
                    location: kiosk.assignedRoomName || "Not Assigned",
                    osVersion: "Raspberry Pi OS (64-bit)",
                    appVersion: "v1.0.0",
                    ...kiosk,
                });
            }
        } catch (err) {
            console.error("Failed to re-fetch device info", err);
        }
    };

    const [csvFile, setCsvFile] = useState(null);

    const handleFileChange = (event) => {
        const file = event.target.files[0];
        if (file && file.name.endsWith(".csv")) {
            setCsvFile(file);
            alert(`CSV file selected: ${file.name}`);
        } else {
            alert("Please select a valid CSV file.");
        }
    };

    return (
        <div className="relative flex justify-center items-center w-full h-full text-white">
            <div className="bg-gray-700/80 mt-8 rounded-2xl shadow-lg flex overflow-hidden w-[1220px] h-[600px]">
                <div className="bg-gray-800 w-1/4 p-6 flex flex-col justify-start border-r border-gray-700">
                    <button
                        onClick={() => navigate(-1)}
                        className="flex items-center space-x-2 text-gray-300 hover:text-white transition mb-8"
                    >
                        <FaArrowLeft className="text-xl" />
                        <span className="text-md font-medium">Back</span>
                    </button>

                    {["kiosk", "database", "beta", "system"].map((tab) => (
                        <button
                            key={tab}
                            className={`text-left py-3 px-4 rounded-lg mb-2 transition ${activeTab === tab
                                    ? "bg-gray-700 text-white font-semibold"
                                    : "text-gray-400 hover:bg-gray-700 hover:text-white"
                                }`}
                            onClick={() => setActiveTab(tab)}
                        >
                            {tab === "kiosk"
                                ? "Kiosk Information"
                                : tab === "database"
                                    ? "Database Management"
                                    : tab === "beta"
                                        ? "Beta Test"
                                        : "System Controls"}
                        </button>
                    ))}

                </div>

                <div className="flex-1 p-10 relative overflow-y-auto">
                    {activeTab === "kiosk" && <KioskInfoTab deviceInfo={deviceInfo || {}} onRefresh={refreshRooms} />}
                    {activeTab === "beta" && (
                        <BetaTestTab csvFile={csvFile} handleFileChange={handleFileChange} />
                    )}
                    {activeTab === "system" && <SystemControlsTab />}
                    {activeTab === "database" && <DatabaseManagementTab />}
                </div>
            </div>
        </div>
    );
}

export default SettingsPage;
