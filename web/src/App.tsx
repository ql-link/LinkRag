import { Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider } from '@/contexts/AuthContext';
import { ToastProvider } from '@/contexts/ToastContext';
import { AppLayout } from '@/layouts/AppLayout';
import AccountPage from '@/pages/account/AccountPage';
import AuthPage from '@/pages/auth/AuthPage';
import ChatPage from '@/pages/chat/ChatPage';
import DatasetDetailPage from '@/pages/datasets/DatasetDetailPage';
import DatasetListPage from '@/pages/datasets/DatasetListPage';
import FileDetailPage from '@/pages/datasets/FileDetailPage';
import ParseConfigPage from '@/pages/datasets/ParseConfigPage';
import HomePage from '@/pages/home/HomePage';
import ModelsPage from '@/pages/models/ModelsPage';
import SearchPage from '@/pages/search/SearchPage';
import UsagePage from '@/pages/usage/UsagePage';

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route element={<AppLayout />}>
            <Route index element={<HomePage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:conversationId" element={<ChatPage />} />
            <Route path="datasets" element={<DatasetListPage />} />
            <Route path="datasets/:datasetId" element={<DatasetDetailPage />} />
            <Route path="datasets/:datasetId/config" element={<ParseConfigPage />} />
            <Route path="datasets/:datasetId/files/:fileId" element={<FileDetailPage />} />
            <Route path="models" element={<ModelsPage />} />
            <Route path="usage" element={<UsagePage />} />
            <Route path="account" element={<AccountPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </ToastProvider>
  );
}
