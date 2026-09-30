import { AlertCircle, Inbox, KeyRound } from 'lucide-react';
import type { ReactNode } from 'react';

import { Spinner } from '@/components/ui/Loading';
import { cn } from '@/lib/cn';

type Kind = 'loading' | 'error' | 'empty' | 'denied';
type Size = 'page' | 'card' | 'inline';

const ICONS: Record<Kind, ReactNode> = {
  loading: <Spinner className="size-4" />,
  error: <AlertCircle aria-hidden className="size-3.5 text-red" />,
  empty: <Inbox aria-hidden className="size-3.5 text-muted" />,
  denied: <KeyRound aria-hidden className="size-3.5 text-text2" />,
};

/**
 * 统一的加载中 / 加载失败 / 空态 / 无权限反馈（设计稿 State/Feedback）。
 * 加载失败必须提供「重新加载」；切换筛选或刷新失败时保留旧数据，改用 {@link StaleBanner}。
 */
export function StateFeedback({ kind, size = 'card', title, desc, action, className }: { kind: Kind; size?: Size; title: string; desc?: ReactNode; action?: ReactNode; className?: string }) {
  if (size === 'inline')
    return (
      <div role={kind === 'error' ? 'alert' : 'status'} className={cn('flex items-center justify-center gap-2 py-6 text-[12px] text-muted', className)}>
        {ICONS[kind]}
        <span>{title}</span>
        {action}
      </div>
    );
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={cn('mx-auto flex w-full max-w-[420px] flex-col items-center gap-3 px-8 text-center', size === 'page' ? 'py-16' : 'py-10', className)}>
      <span className={cn('flex items-center justify-center rounded-[14px] bg-soft', size === 'page' ? 'size-[52px]' : 'size-10 rounded-[10px]')}>{ICONS[kind]}</span>
      <p className={cn('font-semibold text-ink', size === 'page' ? 'font-serif text-[20px]' : 'text-[14px]')}>{title}</p>
      {desc && <p className="text-[13px] leading-5 text-muted">{desc}</p>}
      {action}
    </div>
  );
}

/** 刷新 / 切换筛选失败时的顶部黄色提示条：保留旧数据 */
export function StaleBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="mb-4 flex items-center gap-2 rounded-[10px] border border-amber/25 bg-amber/10 px-3.5 py-2.5 text-[12px] text-[#8a5a14]">
      <AlertCircle aria-hidden className="size-3.5 shrink-0" />
      <span className="min-w-0 flex-1">{message}，当前展示的是上一次成功加载的数据。</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="shrink-0 font-medium underline-offset-2 hover:underline">
          重新加载
        </button>
      )}
    </div>
  );
}

export const actionBtn = 'rounded-[7px] border border-line bg-white px-3.5 py-2 text-[12px] font-medium text-text2 transition-colors hover:bg-soft';
