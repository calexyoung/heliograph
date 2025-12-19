import { Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import LoginPage from './pages/LoginPage';
import UploadPage from './pages/UploadPage';
import SearchPage from './pages/SearchPage';
import CorpusPage from './pages/CorpusPage';
import ChatPage from './pages/ChatPage';
import GraphPage from './pages/GraphPage';
import DocumentPage from './pages/DocumentPage';

function App() {
  return (
    <>
    <Toaster position="top-right" />
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="corpus" element={<CorpusPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="documents/:documentId" element={<DocumentPage />} />
      </Route>
    </Routes>
    </>
  );
}

export default App;
