import React from "react";
import { FaFileImport } from "react-icons/fa";

function BetaTestTab({ csvFile, handleFileChange }) {
  return (
    <div className="animate-fadeIn mt-8 flex flex-col items-center text-center">
      <h2 className="text-3xl font-bold mb-4">Beta Test</h2>
      <p className="text-gray-300 mb-6 max-w-md">
        Import a test CSV file here to simulate data synchronization or
        local database updates.
      </p>

      <label className="flex flex-col items-center justify-center cursor-pointer bg-gray-700 hover:bg-gray-600 transition rounded-lg px-6 py-4 w-full max-w-xs">
        <FaFileImport className="text-4xl mb-2 text-white" />
        <span className="text-lg font-medium">
          {csvFile ? `Selected: ${csvFile.name}` : "Choose CSV File"}
        </span>
        <input
          type="file"
          accept=".csv"
          className="hidden"
          onChange={handleFileChange}
        />
      </label>
    </div>
  );
}

export default BetaTestTab;
