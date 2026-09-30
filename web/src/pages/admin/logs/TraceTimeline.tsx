/** trace_id 追踪（设计稿 E2）：同一链路日志按时间升序排列，显示相对首条的耗时偏移 */
import { X } from 'lucide-react';

import { Card } from '../ui';
import { fmtSpan, parseLogTime, type LogEntry } from './api';
import { LevelBadge } from './LevelBadge';

export function traceSteps(items: LogEntry[]) {
  const rows = items
    .map((it, index) => ({ it, index, t: parseLogTime(it.time)?.getTime() ?? NaN }))
    .filter((r) => !Number.isNaN(r.t))
    .sort((a, b) => a.t - b.t);
  const t0 = rows[0]?.t ?? 0;
  const span = rows.length ? rows[rows.length - 1].t - t0 : 0;
  return { rows: rows.map((r) => ({ ...r, offset: r.t - t0 })), span, services: [...new Set(rows.map((r) => r.it.service).filter(Boolean))] as string[] };
}

export function TraceTimeline({ traceId, items, onSelect, onClear }: { traceId: string; items: LogEntry[]; onSelect: (index: number) => void; onClear: () => void }) {
  const { rows, span, services } = traceSteps(items);
  return (
    <Card className="mb-5 px-5 py-4">
      <div className="flex items-center gap-3">
        <p className="text-[13px] font-medium text-ink">链路追踪</p>
        <span className="font-mono text-[11.5px] text-text2">{traceId}</span>
        <span className="text-[11px] text-muted">
          {rows.length} 条 · 跨度 {fmtSpan(span)} · {services.join(' → ') || '未知服务'}
        </span>
        <button type="button" onClick={onClear} className="ml-auto flex items-center gap-1 text-[11.5px] text-muted hover:text-ink">
          <X aria-hidden className="size-3.5" />
          清除 trace
        </button>
      </div>
      {rows.length > 0 && (
        <ol className="mt-3.5 flex flex-col gap-1.5">
          {rows.map(({ it, index, offset }) => {
            const pct = span > 0 ? (offset / span) * 100 : 0;
            return (
              <li key={index}>
                <button type="button" onClick={() => onSelect(index)} className="grid w-full grid-cols-[60px_52px_110px_160px_1fr] items-center gap-3 rounded-[6px] px-1.5 py-1 text-left hover:bg-soft">
                  <span className="font-num text-[11px] text-muted tabular-nums">+{fmtSpan(offset)}</span>
                  <LevelBadge level={it.level} />
                  <span className="truncate font-num text-[11px] text-text2">{it.service ?? '—'}</span>
                  <span aria-hidden className="relative h-2">
                    <span className="absolute inset-x-0 top-1/2 h-px bg-divider" />
                    <span className="absolute top-0 size-2 -translate-x-1/2 rounded-full bg-ink" style={{ left: `${pct}%` }} />
                  </span>
                  <span className="min-w-0 truncate text-[11.5px] text-ink">{it.message ?? '—'}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
