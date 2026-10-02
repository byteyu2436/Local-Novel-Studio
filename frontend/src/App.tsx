import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import DiagnosticsPage from "@/pages/DiagnosticsPage";
import HomePage from "@/pages/HomePage";
import ImportPreviewPage from "@/pages/ImportPreviewPage";
import InitializePage from "@/pages/InitializePage";
import MemoryCenterPage from "@/pages/MemoryCenterPage";
import PasteImportPage from "@/pages/PasteImportPage";
import ReaderPage from "@/pages/ReaderPage";
import RetrievalDebugPage from "@/pages/RetrievalDebugPage";
import TxtImportPage from "@/pages/TxtImportPage";
import WritingGatePage from "@/pages/WritingGatePage";
import WritingWorkspacePage from "@/pages/WritingWorkspacePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/import" element={<PasteImportPage />} />
        <Route path="/import/txt" element={<TxtImportPage />} />
        <Route
          path="/imports/:sourceId/preview"
          element={<ImportPreviewPage />}
        />
        <Route path="/novels/:novelId/memory" element={<MemoryCenterPage />} />
        <Route
          path="/novels/:novelId/initialize"
          element={<InitializePage />}
        />
        <Route path="/novels/:novelId/write" element={<WritingGatePage />} />
        <Route
          path="/novels/:novelId/workspace"
          element={<WritingWorkspacePage />}
        />
        <Route
          path="/dev/novels/:novelId/retrieval"
          element={<RetrievalDebugPage />}
        />
        <Route path="/novels/:novelId" element={<ReaderPage />} />
        <Route
          path="/novels/:novelId/chapters/:chapterId"
          element={<ReaderPage />}
        />
        <Route path="/diagnostics" element={<DiagnosticsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
