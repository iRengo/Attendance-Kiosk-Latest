import React, { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { FaChevronLeft, FaInfoCircle, FaExclamationTriangle, FaCheckCircle } from "react-icons/fa";

const sampleData = [
  {
    notif_id: "notif-sample-1",
    kiosk_id: "kiosk-1",
    title: "Unknown face detected",
    type: "alert",
    priority: 1,
    is_read: false,
    timestamp: new Date().toISOString(),
    class_id: "class-101",
    teacher: "Unknown",
    image_url: "",
    raw_doc: { reason: "face_not_recognized" },
    createdAt: new Date().toISOString(),
  },
  {
    notif_id: "notif-sample-2",
    kiosk_id: "kiosk-1",
    title: "Sync completed",
    type: "info",
    priority: 2,
    is_read: true,
    timestamp: new Date().toISOString(),
    class_id: null,
    teacher: "system",
    image_url: "",
    raw_doc: {},
    createdAt: new Date().toISOString(),
  },
];

export default function KioskNotifications() {
  const navigate = useNavigate();
  const [notes, setNotes] = useState([]);
  const [filter, setFilter] = useState("all");

  const formatRelative = (iso) => {
    try {
      const then = new Date(iso).getTime();
      const diff = Date.now() - then;
      const sec = Math.floor(diff / 1000);
      if (sec < 60) return `${sec}s ago`;
      const min = Math.floor(sec / 60);
      if (min < 60) return `${min}m ago`;
      const hr = Math.floor(min / 60);
      if (hr < 24) return `${hr}h ago`;
      const day = Math.floor(hr / 24);
      if (day < 7) return `${day}d ago`;
      return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (e) {
      return '';
    }
  };

  useEffect(() => {
    const fetchNotes = async () => {
      try {
        const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
        const res = await axios.get(`${API_BASE}/kiosk_notifications`);
        const items = (res.data && res.data.notifications) || [];
        setNotes(items);
      } catch (e) {
        console.error('Failed to load notifications', e);
        setNotes(sampleData);
      }
    };
    fetchNotes();
    const id = setInterval(fetchNotes, 10000); // refresh every 10s
    return () => clearInterval(id);
  }, []);

  const [expanded, setExpanded] = useState(null);

  const markRead = (id) => {
    setNotes((prev) => prev.map((n) => (n.notif_id === id ? { ...n, is_read: true } : n)));
  };

  const markAllRead = () => {
    setNotes((prev) => prev.map((n) => ({ ...n, is_read: true })));
  };

  const filteredNotes = notes
    .filter((n) => {
      if (filter === "unread") return !n.is_read;
      if (filter === "alert") return n.type === "alert";
      if (filter === "info") return n.type === "info";
      if (filter === "success") return n.type === "success";
      return true; // all
    })
    .sort((a, b) => {
      const ta = Date.parse(a.timestamp || a.createdAt || 0) || 0;
      const tb = Date.parse(b.timestamp || b.createdAt || 0) || 0;
      return tb - ta; // newest first
    });

  return (
    <div className="relative flex justify-center w-full h-full text-white">
      <div className="bg-gray-700/80 mt-8 rounded-2xl shadow-lg flex overflow-hidden w-[1220px] h-[600px]">
        {/* Left Sidebar - Filters */}
        <aside className="bg-gray-800 w-1/4 p-6 flex flex-col justify-start border-r border-gray-700">
          <button
            onClick={() => navigate("/landing")}
            className="flex items-center gap-2 text-gray-300 hover:text-white mb-6"
          >
            <FaChevronLeft /> <span>Back</span>
          </button>
          <div className="flex flex-col space-y-2">
            {["all", "unread", "alert", "info", "success"].map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-4 py-2 rounded-xl text-left capitalize text-sm ${
                  filter === f
                    ? "bg-gray-600 text-white"
                    : "bg-gray-800 hover:bg-gray-700 text-gray-300"
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          <div className="mt-auto">
            <button
              onClick={markAllRead}
              className="w-full py-3 px-4 rounded-lg mb-2 bg-gray-700 text-white hover:bg-gray-600"
            >
              Mark All Read
            </button>

            <button
              onClick={() => alert("Notify Admin clicked")}
              className="w-full py-3 px-4 rounded-lg mb-2 bg-gray-700 text-white hover:bg-gray-600"
            >
              Notify Admin
            </button>
          </div>
        </aside>

        {/* Right Section - Notifications */}
        <main className="flex-1 p-8 overflow-y-auto">
          <div className="w-full max-w-4xl mx-auto">
            <h4 className="text-2xl text-left font-semibold mb-6">Notifications</h4>
            <div className="space-y-4">
              {filteredNotes.length === 0 ? (
                <div className="text-gray-400 text-center mt-20">No notifications found</div>
              ) : (
                filteredNotes.map((n) => (
                  <div
                    key={n.notif_id}
                    className={`relative p-4 rounded-xl bg-gray-700/80 border border-gray-600 flex flex-wrap gap-4 items-start shadow-md ${n.is_read ? "opacity-70" : ""}`}
                  >
                    <div className="w-20 h-20 bg-gray-800 rounded overflow-hidden flex items-center justify-center">
                      {n.image_url ? (
                        <img src={n.image_url} alt={n.title} className="w-full h-full object-cover" />
                      ) : n.type === "alert" ? (
                        <FaExclamationTriangle className="text-red-400 text-3xl" />
                      ) : n.type === "warning" ? (
                        <FaExclamationTriangle className="text-amber-400 text-3xl" />
                      ) : n.type === "success" ? (
                        <FaCheckCircle className="text-emerald-400 text-3xl" />
                      ) : (
                        <FaInfoCircle className="text-sky-400 text-3xl" />
                      )}
                    </div>
                    <div className="flex-1 text-left">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-semibold text-lg">{n.title}</div>
                          <div className="text-xs text-gray-300">
                            {new Date(n.timestamp).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs text-gray-300 capitalize">{n.type}</div>
                        </div>
                      </div>

                      <div className="mt-2 text-sm text-gray-200 space-y-1">
                        <div><strong>Kiosk ID:</strong> {n.kiosk_id}</div>
                        <div><strong>Room Name:</strong> {n.room || "—"}</div>
                      </div>

                      {/* small view details button positioned to the right */}
                      <button
                        onClick={() => setExpanded(expanded === n.notif_id ? null : n.notif_id)}
                        className="absolute top-3 right-3 px-2 py-1 text-xs bg-gray-800 rounded-md hover:bg-gray-700"
                      >
                        {expanded === n.notif_id ? 'Hide details' : 'View details'}
                      </button>
                      <div className="absolute bottom-3 right-3 text-xs text-gray-400">{formatRelative(n.timestamp)}</div>
                    </div>
                    {expanded === n.notif_id && (
                      <div className="w-full mt-3 p-3 bg-gray-800 rounded-md text-xs text-gray-200">
                        {typeof n.details === 'string' ? (
                          <div className="whitespace-pre-wrap">{n.details}</div>
                        ) : (
                          <pre className="whitespace-pre-wrap">{JSON.stringify(n.details || n.raw_doc || {}, null, 2)}</pre>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
