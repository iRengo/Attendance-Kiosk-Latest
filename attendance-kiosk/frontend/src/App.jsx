import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import ScreenSaver from "./pages/screenSaver";
import LandingPage from "./pages/landingPage";
import ClassHistory from "./pages/classHistory";
import SettingsPage from "./pages/systemSettings";
import SystemService from "./pages/systemService";
import KioskNotifications from "./pages/kioskNotifications";
import { useEffect, useState } from "react";

import "./App.css";
import LoadingOverlay from "./components/common/LoadingOverlay";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function App() {
  const [overlayVisible, setOverlayVisible] = useState(false);
  const [overlayMessage, setOverlayMessage] = useState("");

  useEffect(() => {
    // Expose simple global helpers so non-React code (or axios interceptors)
    // can trigger the overlay while /sync is in-flight.
    window.__showSyncOverlay = (msg = "Syncing...") => {
      setOverlayMessage(msg);
      setOverlayVisible(true);
    };
    window.__hideSyncOverlay = () => {
      setOverlayVisible(false);
      setOverlayMessage("");
    };

    // Periodically check backend health. If the backend is unreachable,
    // show overlay with a friendly message until it becomes available.
    let mounted = true;
    const check = async () => {
      try {
        const resp = await fetch(`${API_BASE}/device/info`, { cache: "no-store" });
        if (!mounted) return;
        // backend responded; hide startup overlay
        if (resp && resp.ok) {
          window.__hideSyncOverlay && window.__hideSyncOverlay();
        } else {
          // backend responded with error: still consider it available
          window.__hideSyncOverlay && window.__hideSyncOverlay();
        }
      } catch (e) {
        if (!mounted) return;
        // network error - likely server not yet started
        window.__showSyncOverlay && window.__showSyncOverlay("Starting backend...");
      }
    };

    // run immediately and then every 3s
    check();
    const id = setInterval(check, 3000);
    return () => {
      mounted = false;
      clearInterval(id);
      // cleanup globals
      try {
        delete window.__showSyncOverlay;
        delete window.__hideSyncOverlay;
      } catch (e) {}
    };
  }, []);

  return (
    <>
      <Router>
        <Routes>
          <Route path="/" element={<ScreenSaver />} />
          <Route path="/landing" element={<LandingPage />} />
          <Route path="/systemService" element={<SystemService />} />
          <Route path="/kioskNotifications" element={<KioskNotifications />} />
          <Route path="/classHistory" element={<ClassHistory />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </Router>
      <LoadingOverlay visible={overlayVisible} message={overlayMessage} />
    </>
  );
}

export default App;
