/** 日志表格（设计稿 E1 Head / LogRow）：点击行打开详情，点击 trace_id 按链路筛选 */
import { ChevronRight } from 'lucide-react';

import { Chip } from '@/components/ui/Chip';
import { cn } from '@/lib/cn';

import { th } from '../ui';
import { fmtClock, type LogEntry } from './api';
import { LevelBadge } from './LevelBadge';

interface Props {
  items: LogEntry[];
  selected: number | null;
  onSelect: (index: number) => void;
  onTrace: (traceId: string) => void;
  /** 当前按 trace 追踪时高亮该 trace_id */
  activeTrace?: string;
}

export function LogTable({ items, selected, onSelect, onTrace, activeTrace }: Props) {
  const now = new Date();
  return (
    <table className="w-full table-fixed border-collapse">
      <thead>
        <tr className="border-b border-divider">
          <th scope="col" className={cn(th, 'w-[108px]')}>时间</th>
          <th scope="col" className={cn(th, 'w-[68px]')}>级别</th>
          <th scope="col" className={cn(th, 'w-[118px]')}>服务</th>
          <th scope="col" className={cn(th, 'w-[118px]')}>trace_id</th>
          <th scope="col" className={th}>message</th>
          <th scope="col" className={cn(th, 'w-5')}>
            <span className="sr-only">详情</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((it, i) => {
          const on = selected === i;
          return (
            <tr
              key={`${it.time}-${i}`}
              tabIndex={0}
              aria-selected={on}
              onClick={() => onSelect(i)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelect(i);
                }
              }}
              className={cn('cursor-pointer border-b border-divider transition-colors outline-none hover:bg-soft/60 focus-visible:bg-soft', on && 'bg-soft')}
            >
              <td className="py-[11px] font-num text-[11.5px] text-text2 tabular-nums" title={it.time}>
                {fmtClock(it.time, now)}
              </td>
              <td className="py-[10px]">
                <LevelBadge level={it.level} />
              </td>
              <td className="truncate py-[11px] font-num text-[11.5px] text-text2">{it.service ?? '—'}</td>
              <td className="py-[11px]">
                {it.trace_id ? (
                  <button
                    type="button"
                    title="按此 trace_id 追踪"
                    onClick={(e) => {
                      e.stopPropagation();
                      onTrace(it.trace_id!);
                    }}
                    className={cn('max-w-full truncate font-mono text-[11px] underline-offset-2 hover:text-ink hover:underline', activeTrace === it.trace_id ? 'font-semibold text-ink' : 'text-blue')}
                  >
                    {it.trace_id}
                  </button>
                ) : (
                  <span className="text-[11px] text-muted">—</span>
                )}
              </td>
              <td className="py-[10px] text-[12px] text-ink">
                <span className="flex min-w-0 items-center gap-2">
                  {it.exception && (
                    <Chip tone="red" dot={false}>
                      异常
                    </Chip>
                  )}
                  <span className="min-w-0 truncate">{it.message ?? it.raw ?? '—'}</span>
                </span>
              </td>
              <td className="py-[11px] text-muted">
                <ChevronRight aria-hidden className="size-3.5" />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
