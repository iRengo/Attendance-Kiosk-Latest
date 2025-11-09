import React, { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { FaChevronLeft } from "react-icons/fa";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export default function ClassHistory() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const itemsPerPage = 3; // show up to 3 cards per page
  const navigate = useNavigate();

  useEffect(() => {
    const fetchHistory = async () => {
      setLoading(true);
      try {
        const res = await axios.get(`${API_BASE}/session/history?limit=200`);
        const items = (res.data && res.data.history) || [];
        // Ensure newest -> oldest order. Prefer explicit time fields; fall back to id order.
        items.sort((a, b) => {
          const aTime = new Date(a.timeStarted || a.date || a.createdAt || 0).getTime();
          const bTime = new Date(b.timeStarted || b.date || b.createdAt || 0).getTime();
          // if both times are valid, sort by descending time (newest first)
          if (!isNaN(aTime) && !isNaN(bTime)) return bTime - aTime;
          // fallback: if one has time, prefer it
          if (!isNaN(aTime)) return -1;
          if (!isNaN(bTime)) return 1;
          // final fallback: keep original order
          return 0;
        });
        setHistory(items);

        const teacherIds = Array.from(
          new Set(items.map((it) => it.teacher_id).filter(Boolean))
        );

        if (teacherIds.length) {
          const tres = await axios.get(`${API_BASE}/teachers`, {
            params: { ids: teacherIds.join(",") },
          });
          const teachers = tres.data?.teachers || [];
          const byId = {};
          teachers.forEach((t) => {
            byId[String(t.id)] = t;
          });

          setHistory((prev) =>
            prev.map((h) => {
              const t = byId[String(h.teacher_id)];
              if (t) {
                const name = `${(t.firstname || "").trim()} ${(t.lastname || "").trim()}`.trim();
                return {
                  ...h,
                  teacher_name: name,
                  teacher_profilePicUrl: t.profilePicUrl || "",
                };
              }
              return h;
            })
          );
        }
      } catch (e) {
        console.error(e);
        setError("Failed to load class history");
      } finally {
        setLoading(false);
      }
    };
    fetchHistory();
  }, []);

  const startIndex = (page - 1) * itemsPerPage;
  const paginated = history.slice(startIndex, startIndex + itemsPerPage);
  const totalPages = Math.ceil(history.length / itemsPerPage);

  return (
    <div className="relative w-full h-full flex flex-col items-start px-8 py-8 text-white overflow-auto">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={() => navigate("/landing")}
          className="p-2 rounded-md"
        >
          <FaChevronLeft />
        </button>
        <h4 className="text-xl font-semibold">Class History</h4>
      </div>

      {/* Loading / Error */}
      {loading && <div className="text-gray-400">Loading...</div>}
      {error && <div className="text-red-400">{error}</div>}

      {/* Content */}
      {!loading && !error && (
        <>
          {history.length === 0 ? (
            <div className="text-gray-400 text-center">No class history available.</div>
          ) : (
            <>
              <div className="mx-auto mt-4 w-full max-w-2xl sm:max-w-4xl md:max-w-6xl">
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
                  {paginated.map((h) => {
                    const subj =
                      h.subjectName ||
                      h.subject ||
                      h.class_name ||
                      h.class_code ||
                      "Untitled Class";
                    // date for card (prefer explicit date fields then fallback to timeStarted)
                    let displayDate = "-";
                    try {
                      const rawDate = h.date || h.createdAt || h.timeStarted || null;
                      if (rawDate) {
                        const d = new Date(rawDate);
                        if (!isNaN(d.getTime())) displayDate = d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
                      }
                    } catch (e) {
                      displayDate = "-";
                    }
                    const room = h.room_fs_id || h.room || "Room";
                    const teacherImg =
                      h.teacher_profilePicUrl ||
                      (h.raw_doc?.teacher?.profilePicUrl ?? "");
                    const timeIn = h.timeStarted
                      ? new Date(h.timeStarted).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "-";
                    const timeOut = h.timeEnded
                      ? new Date(h.timeEnded).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "-";

                    return (
                      <div
                        key={h.id}
                        className="rounded-xl overflow-hidden shadow-md hover:shadow-lg transition transform hover:-translate-y-1 border border-gray-700 bg-transparent"
                      >
                        {/* Header: subject + larger avatar with distinct background */}
                        <div className="p-4 bg-gray-700/80 text-white font-bold text-lg flex justify-between items-center border-b border-gray-600">
                          <div className="text-left">
                            <div className="text-lg font-bold">{subj}</div>
                            <div className="text-xs text-gray-300 mt-1">{displayDate}</div>
                          </div>
                          <div className="w-14 h-14 rounded-full overflow-hidden bg-gray-200 flex items-center justify-center">
                            {teacherImg ? (
                              <img
                                src={teacherImg.startsWith("/") ? `${API_BASE}${teacherImg}` : teacherImg}
                                alt={h.teacher_name || "teacher"}
                                className="w-full h-full object-cover"
                              />
                            ) : (
                              <svg
                                className="w-10 h-10 text-gray-400"
                                viewBox="0 0 24 24"
                                fill="currentColor"
                              >
                                <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4z" />
                                <path d="M4 20c0-2.21 3.58-4 8-4s8 1.79 8 4v1H4v-1z" />
                              </svg>
                            )}
                          </div>
                        </div>

                        {/* Body: details with room badge above teacher name, separator already added via border-b */}
                        <div className="p-6 space-y-3 text-left text-gray-200 text-sm bg-transparent">
                          <div>
                            <div className="inline-block bg-gray-800 text-white text-xs font-semibold px-3 py-1 rounded-full">{room}</div>
                          </div>

                          <p>
                            <span className="font-semibold text-white">Teacher:</span>{" "}
                            <span className="text-left">{h.teacher_name || h.teacher_id || "—"}</span>
                          </p>

                          <p>
                            <span className="font-semibold text-white">Present Students:</span>{" "}
                            <span className="text-left">{h.students_present_total ?? 0}</span>
                          </p>

                          <div className="pt-2 border-t border-gray-700" />

                          <div className="flex gap-4">
                            <div>
                              <p className="text-xs text-gray-400">Time In</p>
                              <p className="font-medium text-white">{timeIn}</p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-400">Time Out</p>
                              <p className="font-medium text-white">{timeOut}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Pagination: left = "Page X of Y", center = dots, right = Prev/Next */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between mt-8 w-full max-w-6xl mx-auto">
                  {/* Left: page text */}
                  <div className="text-sm text-gray-400">Page {page} of {totalPages}</div>

                  {/* Center: dots indicator (small white dot for current) */}
                  <div className="flex items-center gap-2">
                    {Array.from({ length: totalPages }).map((_, i) => (
                      <button
                        key={i}
                        onClick={() => setPage(i + 1)}
                        aria-label={`Go to page ${i + 1}`}
                        className={`w-3 h-3 rounded-full transition ${page === i + 1 ? 'bg-white' : 'bg-gray-500'}`}
                      />
                    ))}
                  </div>

                  {/* Right: prev/next controls */}
                  <div className="flex items-center gap-3">
                    <button
                      disabled={page === 1}
                      onClick={() => setPage((p) => p - 1)}
                      className={`px-4 py-1 rounded-md border ${
                        page === 1
                          ? "text-gray-500 font-bold border-gray-600"
                          : "text-white-500 border-blue-500"
                      }`}
                    >
                      Previous
                    </button>
                    <button
                      disabled={page === totalPages}
                      onClick={() => setPage((p) => p + 1)}
                      className={`px-4 py-1 rounded-md border ${
                        page === totalPages
                          ? "text-gray-500 font-bold border-gray-600"
                          : "text-white-500 border-gray-500 "
                      }`}
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
