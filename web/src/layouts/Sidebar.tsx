import { ChartColumn, Cpu, Database, House, Plus, Search, ShieldCheck } from 'lucide-react';
import type { ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';

import { ConversationList } from './ConversationList';

import { Brand } from '@/components/brand/Brand';
import { useAuth } from '@/contexts/AuthContext';
import { useSearch } from '@/contexts/SearchContext';
import { cn } from '@/lib/cn';
import { useStore } from '@/services/useStore';

const itemBase = 'flex h-[30px] w-full items-center gap-2 rounded-[7px] px-3 text-[12.5px] text-text2 transition-colors hover:bg-active/60';
const itemActive = 'bg-active font-medium text-ink';

function NavItem({ to, icon, label, badge, end }: { to: string; icon: ReactNode; label: string; badge?: number; end?: boolean }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => cn(itemBase, isActive && itemActive)}>
      <span className="flex size-3.5 items-center [&>svg]:size-3.5">{icon}</span>
      {label}
      {badge !== undefined && <span className="ml-auto font-num text-[10px] font-medium text-muted">{badge}</span>}
    </NavLink>
  );
}

/** 应用侧栏（Figma Sidebar 2:2）：导航 + 对话区 + 用户信息 */
export function Sidebar() {
  const datasetCount = useStore((s) => s.datasets.length);
  const { user } = useAuth();
  const navigate = useNavigate();
  const { openPalette } = useSearch();

  return (
    <aside className="flex h-full w-[216px] shrink-0 flex-col px-3.5 pt-6 pb-5">
      <Brand className="pl-2" />
      <div className="h-[18px]" />
      <button type="button" onClick={() => openPalette()} aria-keyshortcuts="Meta+K" className={cn(itemBase, 'text-[12px] text-muted')}>
        <Search aria-hidden className="size-3.5" />
        搜索
        <span className="ml-auto font-num text-[10px] font-medium text-faint">⌘K</span>
      </button>
      <div className="h-2.5" />
      <nav aria-label="主导航" className="flex flex-col">
        <NavItem to="/" end icon={<House />} label="首页" />
        <NavItem to="/datasets" icon={<Database />} label="知识库" badge={datasetCount} />
        <NavItem to="/models" icon={<Cpu />} label="模型配置" />
        <NavItem to="/usage" icon={<ChartColumn />} label="用量" />
        {user?.role === 'ADMIN' && <NavItem to="/admin" icon={<ShieldCheck />} label="管理台" />}
      </nav>
      <div className="h-[22px]" />
      <div className="flex h-5 items-center px-3 text-[10px] text-muted">
        对话
        <button type="button" onClick={() => navigate('/chat')} aria-label="新建对话" className="ml-auto rounded p-0.5 hover:bg-active">
          <Plus className="size-3" />
        </button>
      </div>
      <NavLink to="/chat" end className={({ isActive }) => cn(itemBase, 'shrink-0', isActive && itemActive)}>
        <Plus aria-hidden className="size-3.5" />
        新建对话
      </NavLink>
      <ConversationList />
      <div className="h-4 shrink-0" />
      <NavLink
        to="/account"
        aria-label="用户信息"
        className={({ isActive }) => cn('flex w-full items-center gap-2 rounded-[7px] py-1 pl-2 text-left hover:bg-active/60', isActive && 'bg-active')}
      >
        <span className="flex size-[30px] shrink-0 items-center justify-center rounded-full bg-ink text-[12px] font-medium text-white">
          {user?.displayName.slice(0, 1).toUpperCase()}
        </span>
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-[12px] font-medium text-ink">{user?.displayName}</span>
          <span className="truncate text-[10px] text-muted">{user?.email}</span>
        </span>
      </NavLink>
    </aside>
  );
}
