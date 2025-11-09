import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import axios from 'axios'

// Install lightweight interceptors to toggle the global overlay when
// a /sync request is in-flight. The overlay helpers are created by App
// (window.__showSyncOverlay / window.__hideSyncOverlay). Interceptors
// are tolerant of those helpers not being present yet.
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

axios.interceptors.request.use(
  (config) => {
    try {
      const url = (config.url || '').toString();
      if (url.includes('/sync')) {
        window.__showSyncOverlay && window.__showSyncOverlay('Syncing...');
      }
    } catch (e) {}
    return config;
  },
  (err) => Promise.reject(err)
);

axios.interceptors.response.use(
  (res) => {
    try {
      const url = (res.config && res.config.url) ? res.config.url.toString() : '';
      if (url.includes('/sync')) {
        window.__hideSyncOverlay && window.__hideSyncOverlay();
      }
    } catch (e) {}
    return res;
  },
  (err) => {
    try {
      const cfg = err.config || {};
      if ((cfg.url || '').toString().includes('/sync')) {
        window.__hideSyncOverlay && window.__hideSyncOverlay();
      }
    } catch (e) {}
    return Promise.reject(err);
  }
);

// Wrap fetch to detect client-side calls to /sync as well (some components
// use fetch instead of axios). Keep original behavior otherwise.
if (typeof window !== 'undefined' && window.fetch) {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    try {
      const url = typeof input === 'string' ? input : (input && input.url) ? input.url : '';
      if (url && url.includes('/sync')) {
        window.__showSyncOverlay && window.__showSyncOverlay('Syncing...');
      }
      const r = await originalFetch(input, init);
      if (url && url.includes('/sync')) {
        window.__hideSyncOverlay && window.__hideSyncOverlay();
      }
      return r;
    } catch (e) {
      try {
        const url = typeof input === 'string' ? input : (input && input.url) ? input.url : '';
        if (url && url.includes('/sync')) {
          window.__hideSyncOverlay && window.__hideSyncOverlay();
        }
      } catch (e2) {}
      throw e;
    }
  };
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
