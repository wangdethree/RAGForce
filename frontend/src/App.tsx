import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/AppLayout';
import Dashboard from './pages/admin/Dashboard';
import KnowledgeBaseList from './pages/admin/KnowledgeBaseList';
import KnowledgeBaseDetail from './pages/admin/KnowledgeBaseDetail';
import ChatPage from './pages/chat/ChatPage';
import AuditLogs from './pages/admin/AuditLogs';
import Settings from './pages/admin/Settings';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="knowledge-bases" element={<KnowledgeBaseList />} />
        <Route path="knowledge-bases/:kbId" element={<KnowledgeBaseDetail />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="audit-logs" element={<AuditLogs />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
