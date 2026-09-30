import { LoaderCircle } from 'lucide-react';
import { useEffect, useState, useSyncExternalStore } from 'react';

import { pending } from '@/api/pending';
import { cn } from '@/lib/cn';

/**
 * 统一的加载中间状态：
 * - TopProgress：内容面板顶部细进度条，任一接口请求进行中即显示（由 api/pending 驱动）；
 * - AppLoading：登录后首轮数据装载完成前的整体加载界面；
 * - PageLoading：页面所需接口全部返回前的整页加载状态（页面不分块陆续展示）；
 * - Skeleton：占位块，尺寸由调用方决定，保持加载前后布局一致。
 */

/** 请求超过 150ms 才显示，避免快速请求造成闪烁 */
export function TopProgress() {
  const busy = useSyncExternalStore(pending.subscribe, () => pending.get() > 0);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!busy) return setShown(false);
    const t = setTimeout(() => setShown(true), 150);
    return () => clearTimeout(t);
  }, [busy]);
  return (
    <div
      role="progressbar"
      aria-label="正在加载"
      aria-hidden={!shown}
      className={cn('pointer-events-none absolute inset-x-0 top-0 z-20 h-[2px] overflow-hidden transition-opacity duration-200', shown ? 'opacity-100' : 'opacity-0')}
    >
      <div className="h-full w-1/3 animate-progress-slide rounded-full bg-ink/70" />
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle aria-hidden className={cn('size-4 animate-spin text-muted', className)} />;
}

export function PageLoading({ label = '正在加载…', className }: { label?: string; className?: string }) {
  return (
    <div role="status" aria-live="polite" className={cn('flex items-center justify-center gap-2 py-24 text-[13px] text-muted', className)}>
      <Spinner />
      {label}
    </div>
  );
}

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div aria-hidden style={style} className={cn('animate-pulse rounded-lg bg-soft', className)} />;
}

/** 登录后首屏：模型 / 知识库 / 对话全部装载完成前覆盖整个应用，避免各区块陆续出现 */
export function AppLoading({ logo }: { logo: string }) {
  return (
    <div role="status" aria-live="polite" className="flex h-full flex-col items-center justify-center gap-4 bg-page">
      <img src={logo} alt="" width={40} height={40} className="animate-pulse object-contain" />
      <span className="flex items-center gap-2 text-[12.5px] text-muted">
        <Spinner className="size-3.5" />
        正在加载工作区…
      </span>
    </div>
  );
}
