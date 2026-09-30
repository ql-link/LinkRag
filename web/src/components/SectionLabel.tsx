import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

/** 区块小标题：11px 灰字 + 可选数量 + 右侧操作 */
export function SectionLabel({ label, count, action, className }: { label: string; count?: number; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-center gap-1.5 text-[11px]', className)}>
      <h2 className="font-normal text-muted">{label}</h2>
      {count !== undefined && <span className="font-num font-medium text-faint">{count}</span>}
      {action && <div className="ml-auto flex items-center">{action}</div>}
    </div>
  );
}
