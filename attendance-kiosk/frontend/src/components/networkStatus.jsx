import { useEffect, useState } from "react";
import { Wifi, WifiOff } from "lucide-react";
import axios from "axios";

function NetworkStatus() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [backendOnline, setBackendOnline] = useState(null);

  useEffect(() => {
    const updateNetworkStatus = () => setIsOnline(navigator.onLine);

    window.addEventListener("online", updateNetworkStatus);
    window.addEventListener("offline", updateNetworkStatus);

    const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

    let cancelled = false;

    const pollBackend = async () => {
      try {
        const res = await axios.get(`${API_BASE}/monitor/status`, { timeout: 2000 });
        const s = res.data && res.data.status;
        if (!cancelled && s && typeof s === 'object') {
          if (typeof s.online === 'boolean') {
            setBackendOnline(s.online);
            setIsOnline(s.online);
          }
        }
      } catch (e) {
        // backend unreachable -> treat as offline
        if (!cancelled) {
          setBackendOnline(false);
          setIsOnline(false);
        }
      }
    };

    // initial poll and interval
    pollBackend();
    const id = setInterval(pollBackend, 5000);

    return () => {
      cancelled = true;
      clearInterval(id);
      window.removeEventListener("online", updateNetworkStatus);
      window.removeEventListener("offline", updateNetworkStatus);
    };
  }, []);

  const displayText = backendOnline === false ? "No Internet" : isOnline ? "Connected" : "No Internet";

  return (
    <div className="flex items-center gap-2 select-none">
      {isOnline ? (
        <>
          <Wifi className="w-6 h-6 text-white opacity-80 transition-opacity duration-300" />
          <span className="text-white opacity-80 text-sm font-medium">{displayText}</span>
        </>
      ) : (
        <>
          <WifiOff className="w-6 h-6 text-white opacity-80 transition-opacity duration-300" />
          <span className="text-white opacity-80 text-sm font-medium">{displayText}</span>
        </>
      )}
    </div>
  );
}

export default NetworkStatus;
