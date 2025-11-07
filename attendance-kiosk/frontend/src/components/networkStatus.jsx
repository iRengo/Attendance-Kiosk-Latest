import { useEffect, useState } from "react";
import { Wifi, WifiOff } from "lucide-react";

function NetworkStatus() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    const updateNetworkStatus = () => setIsOnline(navigator.onLine);

    window.addEventListener("online", updateNetworkStatus);
    window.addEventListener("offline", updateNetworkStatus);

    return () => {
      window.removeEventListener("online", updateNetworkStatus);
      window.removeEventListener("offline", updateNetworkStatus);
    };
  }, []);

  return (
    <div className="flex items-center gap-2 select-none">
      {isOnline ? (
        <>
          <Wifi className="w-6 h-6 text-white opacity-80 transition-opacity duration-300" />
          <span className="text-white opacity-80 text-sm font-medium">
            Connected
          </span>
        </>
      ) : (
        <>
          <WifiOff className="w-6 h-6 text-white opacity-80 transition-opacity duration-300" />
          <span className="text-white opacity-80 text-sm font-medium">
            No Internet
          </span>
        </>
      )}
    </div>
  );
}
export default NetworkStatus;
