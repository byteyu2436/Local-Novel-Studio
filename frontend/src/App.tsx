import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import DiagnosticsPage from "@/pages/DiagnosticsPage";
import HomePage from "@/pages/HomePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/diagnostics" element={<DiagnosticsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
