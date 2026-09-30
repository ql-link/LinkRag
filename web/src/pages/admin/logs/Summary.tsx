/** 摘要条（设计稿 E1 Summary）：结果总数 / 当前页 ERROR / 当前页 WARN / 筛选条件 */
import { Fragment, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

export function Summary({ total, error, warn, filters, hint }: { total: string; error: number; warn: number; filters: number; hint?: ReactNode }) {
  const cells: { label: string; value: ReactNode; tone?: string }[] = [
    { label: '结果总数', value: total },
    { label: '当前页 ERROR', value: error, tone: error > 0 ? 'text-red' : undefined },
    { label: '当前页 WARN', value: warn, tone: warn > 0 ? 'text-amber' : undefined },
    { label: '筛选条件', value: `${filters} 项` },
  ];
  return (
    <div className="mb-5 flex items-center border-y border-divider py-3">
      {cells.map((c, i) => (
        <Fragment key={c.label}>
          {i > 0 && <span aria-hidden className="h-10 w-px bg-divider" />}
          <div className="flex flex-1 flex-col gap-1.5 px-5 first:pl-0">
            <p className="text-[11px] text-muted">{c.label}</p>
            <p className={cn('font-num text-[20px] font-semibold text-ink', c.tone)}>{c.value}</p>
          </div>
        </Fragment>
      ))}
      {hint}
    </div>
  );
}
