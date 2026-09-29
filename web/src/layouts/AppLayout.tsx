import { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import logo from '@/assets/brand/logo-mark.png';
import { AppLoading, TopProgress } from '@/components/ui/Loading';
import { useAuth } from '@/contexts/AuthContext';
import { SearchProvider } from '@/contexts/SearchContext';
import { hydrateFromBackend } from '@/services/backend';
import { useBackendReady } from '@/services/useStore';

import { Sidebar } from './Sidebar';

/** 应用外壳：左侧栏 + 右侧白色内容面板（圆角 16，四周 12px 留白） */
export function AppLayout() {
  const { user } = useAuth();
  const location = useLocation();
  const ready = useBackendReady();
  // 幂等：登录流程已触发时复用同一次装载
  useEffect(() => {
    if (user) void hydrateFromBackend();
  }, [user]);
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  // 首轮数据全部装载完成后再一次性展示侧栏与页面
  if (!ready) return <AppLoading logo={logo} />;

  return (
    <SearchProvider>
      <div className="flex h-full min-w-[1080px] bg-page">
        <Sidebar />
        <div className="relative my-3 mr-3 ml-[13px] flex min-w-0 flex-1 overflow-hidden rounded-2xl border border-line bg-white">
          <TopProgress />
          <main className="min-w-0 flex-1 overflow-y-auto">
            <Outlet />
          </main>
        </div>
      </div>
    </SearchProvider>
  );
}

/**
 * 页面内容列：宽度随内容面板流式变化 —— 设计稿基准 860px（1392 宽屏），
 * 面板越宽列越宽（约占 72%），上限 1200px，保证 1920 宽屏下一行 4 张卡片。
 */
export function PageColumn({ children, top = 51 }: { children: React.ReactNode; top?: number }) {
  return (
    <div style={{ paddingTop: top }} className="mx-auto w-[clamp(860px,72%,1200px)] max-w-[calc(100%-48px)] pb-16">
      {children}
    </div>
  );
}
