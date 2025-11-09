import React, { useState, useEffect } from "react";
import { FaWifi } from "react-icons/fa";
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function KioskInfoTab({ deviceInfo }) {
  const serial = deviceInfo?.serial || "Unknown";
  const hostname = deviceInfo?.hostname || deviceInfo?.name || "Unknown";
  // local network state (will be updated from device endpoint)
  const [ipAddr, setIpAddr] = useState(deviceInfo?.ip || deviceInfo?.ipAddress || "Unknown");
  const [macAddr, setMacAddr] = useState(deviceInfo?.mac || deviceInfo?.macAddress || "Unknown");
  const osVersion = deviceInfo?.osVersion || "Unknown";
  const appVersion = deviceInfo?.appVersion || "Unknown";

  const [assignedRoomId, setAssignedRoomId] = useState(deviceInfo?.assignedRoomId || null);
  const [assignedTeacherNames, setAssignedTeacherNames] = useState([]);

  const fetchDeviceAndRoom = async () => {
    try {
      // push local network info to backend (persist into local DB and attempt Firestore)
      try {
        const nres = await axios.post(`${API_BASE}/device/network`);
        const nk = (nres.data && nres.data.kiosk) || null;
        if (nk) {
          if (nk.ipAddress) setIpAddr(nk.ipAddress);
          if (nk.macAddress) setMacAddr(nk.macAddress);
        }
      } catch (e) {
        // ignore
      }

      // fetch kiosk/device info
      const resp = await axios.get(`${API_BASE}/device/info`);
      const data = resp.data || {};
      const k = data.kiosk || data;

  const assignedId = k && (k.assignedRoomId || k.assignedRoom || k.roomId || null);
  setAssignedRoomId(assignedId || null);
    if (k && k.ipAddress) setIpAddr(k.ipAddress);
    if (k && k.macAddress) setMacAddr(k.macAddress);

      if (!assignedId) {
        // nothing to resolve
        setAssignedTeacherNames([]);
        return;
      }

      // fetch rooms and find match
      const rres = await axios.get(`${API_BASE}/rooms`);
      const rooms = (rres.data && rres.data.rooms) || [];
      const matched = rooms.find((r) => String(r.fs_id) === String(assignedId));
      if (!matched) {
        setAssignedTeacherNames([]);
        return;
      }

      // Prefer assignedTeacherId in the room's raw_doc (singular), fall back to assignedTeachers array
      let ids = [];
      try {
        const raw = matched.raw_doc || matched.rawDoc || matched.raw || null;
        let docObj = null;
        if (raw) {
          if (typeof raw === 'string') {
            try { docObj = JSON.parse(raw); } catch (e) { docObj = null; }
          } else if (typeof raw === 'object') {
            docObj = raw;
          }
        }

        if (docObj) {
          // check singular assignedTeacherId (common variants)
          const single = docObj.assignedTeacherId || docObj.assigned_teacher_id || docObj.assignedTeacher || docObj.assigned_teacher || null;
          if (single) {
            ids = [single];
          } else {
            // fall back to array fields
            ids = docObj.assignedTeachers || docObj.assigned_teachers || docObj.assignedteachers || [];
          }
        }

        // final fallback: check matched.assignedteachers field
        if ((!ids || ids.length === 0) && (matched.assignedteachers || matched.assignedTeachers)) {
          const at = matched.assignedteachers || matched.assignedTeachers || null;
          if (at) {
            try { ids = Array.isArray(at) ? at : JSON.parse(at); } catch (e) { ids = Array.isArray(at) ? at : []; }
          }
        }
      } catch (e) {
        ids = [];
      }

      if (!ids || ids.length === 0) {
        setAssignedTeacherNames([]);
        return;
      }

      // resolve teacher names via backend
      try {
        const q = encodeURIComponent(ids.join(","));
        const tres = await axios.get(`${API_BASE}/teachers?ids=${q}`);
        const teachers = (tres.data && tres.data.teachers) || [];
        const byId = {};
        teachers.forEach((t) => { byId[String(t.id)] = t; });
        const names = ids.map((id) => {
          const t = byId[String(id)];
          if (t) return `${(t.firstname || "").trim()} ${(t.lastname || "").trim()}`.trim();
          return String(id);
        });
        setAssignedTeacherNames(names);
      } catch (e) {
        setAssignedTeacherNames(ids.map((i) => String(i)));
      }
    } catch (e) {
      setAssignedTeacherNames([]);
    }
  };

  useEffect(() => { fetchDeviceAndRoom(); }, []);

  return (
    <div className="animate-fadeIn space-y-6 mt-12 text-left">
      <div className="flex justify-between items-start">
        <h2 className="text-3xl font-bold mb-6">Kiosk Information</h2>
        {/* Refresh button removed per request */}
      </div>

      <div className="space-y-2 text-gray-200">
        <p><strong>Serial Number:</strong> {serial}</p>
        <p><strong>Hostname:</strong> {hostname}</p>
  <p><strong>IP Address:</strong> {ipAddr}</p>
  <p><strong>MAC Address:</strong> {macAddr}</p>
  <p><strong>Assigned Room ID:</strong> {assignedRoomId || <span className="text-gray-400">Not Assigned</span>}</p>
        <p><strong>Assigned Teachers:</strong> {assignedTeacherNames && assignedTeacherNames.length > 0 ? assignedTeacherNames.join(", ") : <span className="text-gray-400">None</span>}</p>
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
