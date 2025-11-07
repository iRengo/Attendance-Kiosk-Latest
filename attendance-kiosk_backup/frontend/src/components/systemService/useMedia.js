import { useEffect, useState } from "react";

export function useCameraDevices() {
  const [devices, setDevices] = useState([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    async function getDevices() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        const allDevices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = allDevices.filter(d => d.kind === "videoinput");
        setDevices(videoDevices);
        stream.getTracks().forEach(track => track.stop());
        setError(false);
      } catch (err) {
        console.error("Cannot access camera devices:", err);
        setError(true);
      }
    }
    getDevices();
  }, []);

  return { devices, error };
}
