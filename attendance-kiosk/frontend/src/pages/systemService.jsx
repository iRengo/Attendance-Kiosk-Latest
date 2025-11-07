import React, { useState } from "react";
import TopInfo from "../components/systemService/topInfo";
import CameraFeed from "../components/systemService/cameraFeed";
import BottomInfo from "../components/systemService/bottomInfo";

function SystemService() {
  const [deviceId, setDeviceId] = useState(null);

  return (
<div className="relative w-full h-full text-white bg-gray-700/800 p-3 flex flex-col overflow-hidden">
      
      <TopInfo />

      <hr className="border-gray-700 mb-4" />

      <CameraFeed statusText="Service Started" statusColor="green-500" deviceId={deviceId} />

      <BottomInfo />
    </div>
  );
}

export default SystemService;
