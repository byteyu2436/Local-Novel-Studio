import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import DiagnosticsPage from "@/pages/DiagnosticsPage";
import HomePage from "@/pages/HomePage";
import ImportPreviewPlaceholderPage from "@/pages/ImportPreviewPlaceholderPage";
import PasteImportPage from "@/pages/PasteImportPage";
import TxtImportPage from "@/pages/TxtImportPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/import" element={<PasteImportPage />} />
        <Route path="/import/txt" element={<TxtImportPage />} />
        <Route
          path="/imports/:sourceId/preview"
          element={<ImportPreviewPlaceholderPage />}
        />
        <Route path="/diagnostics" element={<DiagnosticsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
