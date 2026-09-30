import { lazy, Suspense } from 'react';
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

// 落地页动画较重，按需加载，不进入工作台首屏包；根路径 / 始终是落地页（登录与否一致），工作台首页在 /home
const LandingPage = lazy(() => import('@/pages/landing/LandingPage'));
const ResearchPage = lazy(() => import('@/pages/research/ResearchPage'));
const ReportPage = lazy(() => import('@/pages/research/ReportPage'));
const BlogListPage = lazy(() => import('@/pages/blog/BlogListPage'));
const BlogPostPage = lazy(() => import('@/pages/blog/BlogPostPage'));
const FeedbackPage = lazy(() => import('@/pages/feedback/FeedbackPage'));
// 管理台：仅 ADMIN 使用，按需加载
const AdminLayout = lazy(() => import('@/pages/admin/AdminLayout').then((m) => ({ default: m.AdminLayout })));
const AdminOverviewPage = lazy(() => import('@/pages/admin/overview/OverviewPage'));
const AdminUsersPage = lazy(() => import('@/pages/admin/users/UsersPage'));
const AdminUserDetailPage = lazy(() => import('@/pages/admin/users/UserDetailPage'));
const AdminBlogListPage = lazy(() => import('@/pages/admin/blog/BlogAdminListPage'));
const AdminBlogEditorPage = lazy(() => import('@/pages/admin/blog/BlogEditorPage'));
const AdminModelsPage = lazy(() => import('@/pages/admin/models/ModelsAdminPage'));
const AdminLogsPage = lazy(() => import('@/pages/admin/logs/LogsPage'));

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route
            index
            element={
              <Suspense fallback={null}>
                <LandingPage />
              </Suspense>
            }
          />
          <Route
            path="/research"
            element={
              <Suspense fallback={null}>
                <ResearchPage />
              </Suspense>
            }
          />
          <Route
            path="/research/:reportId"
            element={
              <Suspense fallback={null}>
                <ReportPage />
              </Suspense>
            }
          />
          <Route
            path="/blog"
            element={
              <Suspense fallback={null}>
                <BlogListPage />
              </Suspense>
            }
          />
          <Route
            path="/blog/:slug"
            element={
              <Suspense fallback={null}>
                <BlogPostPage />
              </Suspense>
            }
          />
          <Route
            path="/feedback"
            element={
              <Suspense fallback={null}>
                <FeedbackPage />
              </Suspense>
            }
          />
          <Route path="/welcome" element={<Navigate to="/" replace />} />
          <Route
            path="/admin"
            element={
              <Suspense fallback={null}>
                <AdminLayout />
              </Suspense>
            }
          >
            <Route index element={<AdminOverviewPage />} />
            <Route path="users" element={<AdminUsersPage />} />
            <Route path="users/:userId" element={<AdminUserDetailPage />} />
            <Route path="blog" element={<AdminBlogListPage />} />
            <Route path="blog/:postId" element={<AdminBlogEditorPage />} />
            <Route path="models" element={<AdminModelsPage />} />
            <Route path="logs" element={<AdminLogsPage />} />
          </Route>
          <Route element={<AppLayout />}>
            <Route path="home" element={<HomePage />} />
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
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </AuthProvider>
    </ToastProvider>
  );
}
