import { Cpu, FileText, LayoutGrid, MoreHorizontal, ScrollText, Search, Settings, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { Navigate, NavLink, Outlet, useLocation } from 'react-router-dom';

import { Brand } from '@/components/brand/Brand';
import { TopProgress } from '@/components/ui/Loading';
import { useAuth } from '@/contexts/AuthContext';
import { cn } from '@/lib/cn';

import { NoPermission } from './NoPermission';

const itemBase = 'flex h-[30px] w-full items-center gap-2 rounded-[7px] px-3 text-[12.5px] text-text2 transition-colors hover:bg-active/60';
const itemActive = 'bg-active font-medium text-ink';

function NavItem({ to, icon, label, end }: { to: string; icon: ReactNode; label: string; end?: boolean }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => cn(itemBase, isActive && itemActive)}>
      <span className="flex size-3.5 items-center [&>svg]:size-3.5">{icon}</span>
      {label}
    </NavLink>
  );
}

/** 管理台侧栏（设计稿 00 组件 · Sidebar） */
function AdminSidebar() {
  const { user } = useAuth();
  return (
    <aside className="flex h-full w-[216px] shrink-0 flex-col px-3.5 pt-6 pb-5">
      <div className="flex items-center gap-2 pl-2">
        <Brand />
        <span className="rounded-[5px] bg-active px-1.5 py-px text-[10px] font-medium text-text2">管理台</span>
      </div>
      <div className="h-[18px]" />
      <div className="flex h-[30px] items-center gap-2 rounded-[7px] border border-divider bg-white px-3 text-[12px] text-muted">
        <Search aria-hidden className="size-3.5" />
        搜索
        <span className="ml-auto font-num text-[10px] font-medium text-faint">⌘K</span>
      </div>
      <div className="h-3.5" />
      <p className="px-3 py-1 text-[10px] text-muted">管理</p>
      <div className="h-1" />
      <nav aria-label="管理台导航" className="flex flex-col">
        <NavItem to="/admin" end icon={<LayoutGrid />} label="总览" />
        <NavItem to="/admin/users" icon={<Users />} label="用户看板" />
        <NavItem to="/admin/blog" icon={<FileText />} label="博客管理" />
        <NavItem to="/admin/models" icon={<Cpu />} label="模型管理" />
        <NavItem to="/admin/logs" icon={<ScrollText />} label="日志追踪" />
      </nav>
      <div className="h-[18px]" />
      <p className="px-3 py-1 text-[10px] text-muted">系统</p>
      <div className="h-1" />
      <div aria-disabled className={cn(itemBase, 'cursor-default opacity-55 hover:bg-transparent')}>
        <Settings aria-hidden className="size-3.5" />
        配置管理
        <span className="ml-auto rounded-[5px] bg-soft px-1.5 py-px text-[10px] font-medium text-muted">开发中</span>
      </div>
      <span className="flex-1" />
      <div className="flex items-center gap-2.5 px-2.5 py-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-active text-[12px] font-medium text-ink">{user?.displayName.slice(0, 1).toUpperCase()}</span>
        <span className="flex min-w-0 flex-col gap-px">
          <span className="truncate text-[12.5px] font-medium text-ink">{user?.displayName}</span>
          <span className="truncate font-num text-[10.5px] text-muted">{user?.email}</span>
        </span>
        <MoreHorizontal aria-hidden className="ml-auto size-3.5 shrink-0 text-muted" />
      </div>
    </aside>
  );
}

/** 管理台外壳：仅 ADMIN 可进入，其余登录用户看到无权限页（设计稿 A2） */
export function AdminLayout() {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return (
    <div className="flex h-full min-w-[1080px] bg-page">
      <AdminSidebar />
      <div className="relative my-3 mr-3 ml-[13px] flex min-w-0 flex-1 overflow-hidden rounded-2xl border border-line bg-white">
        <TopProgress />
        <main className="min-w-0 flex-1 overflow-y-auto">{user.role === 'ADMIN' ? <Outlet /> : <NoPermission />}</main>
      </div>
    </div>
  );
}

/** 管理台页面内容列（设计稿内容区 1071 宽，左右 40 留白） */
export function AdminColumn({ children, fill }: { children: ReactNode; fill?: boolean }) {
  // fill：内容区撑满可视高度，由页面内部分栏各自滚动（模型目录）
  return <div className={cn('mx-auto w-full max-w-[1200px] px-10 pt-9', fill ? 'flex h-full min-h-[640px] flex-col pb-6' : 'pb-16')}>{children}</div>;
}
