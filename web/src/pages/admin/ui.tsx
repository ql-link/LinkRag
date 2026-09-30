/** 管理台通用组件（设计稿 00 组件）：页头、卡片、下划线标签、分页、数字格式 */
import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

/** 页头：11px 眉标 + 28px 衬线标题 + 13px 说明，右侧操作区底对齐；可接下划线标签，否则接分隔线 */
export function AdminHeader({ eyebrow, title, desc, actions, tabs }: { eyebrow: ReactNode; title: ReactNode; desc?: ReactNode; actions?: ReactNode; tabs?: ReactNode }) {
  return (
    <>
      <header className="flex items-end gap-4">
        <div className="flex min-w-0 flex-col">
          <p className="text-[11px] text-muted">{eyebrow}</p>
          <h1 className="mt-2 font-serif text-[28px] leading-tight font-semibold text-ink">{title}</h1>
          {desc && <p className="mt-1.5 text-[13px] text-text2">{desc}</p>}
        </div>
        {actions && <div className="ml-auto flex shrink-0 items-center gap-2.5">{actions}</div>}
      </header>
      {tabs ? <div className="mt-5">{tabs}</div> : <div className="mt-6 h-px bg-divider" />}
      <div className={tabs ? 'h-6' : 'h-7'} />
    </>
  );
}

/** 下划线标签（用户看板「统计概览 / 用户列表」、模型管理三个视图等） */
export function UnderlineTabs<T extends string>({ items, value, onChange, label }: { items: { value: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-[22px] border-b border-divider">
      {items.map((it) => {
        const on = it.value === value;
        return (
          <button
            key={it.value}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(it.value)}
            className={cn('-mb-px flex items-center gap-1.5 border-b-2 pb-2 text-[13px] transition-colors', on ? 'border-ink font-medium text-ink' : 'border-transparent text-muted hover:text-text2')}
          >
            {it.label}
            {it.count !== undefined && <span className="font-num text-[11px] text-muted">{it.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rounded-[14px] border border-line bg-white shadow-[0_1px_3px_0_rgba(0,0,0,0.04)]', className)}>{children}</div>;
}

/** 卡片标题行：13px 标题 + 右侧 11px 辅助 */
export function CardHead({ title, sub, extra }: { title: ReactNode; sub?: ReactNode; extra?: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex min-w-0 flex-col gap-[3px]">
        <p className="text-[13px] font-medium text-ink">{title}</p>
        {sub && <p className="text-[11px] text-muted">{sub}</p>}
      </div>
      {extra && <div className="ml-auto flex shrink-0 items-center gap-3 text-[11px] text-muted">{extra}</div>}
    </div>
  );
}

/** 分页：显示 a–b / total + 页码 */
export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  const nums: (number | '…')[] = [];
  for (let p = 1; p <= pages; p += 1) {
    if (p === 1 || p === pages || Math.abs(p - page) <= 1) nums.push(p);
    else if (nums[nums.length - 1] !== '…') nums.push('…');
  }
  const btn = 'flex h-7 min-w-7 items-center justify-center rounded-[6px] px-2 font-num text-[11.5px] transition-colors disabled:opacity-40';
  return (
    <nav aria-label="分页" className="flex items-center gap-1 pt-4">
      <span className="mr-auto font-num text-[11.5px] text-muted">
        显示 {fmt(from)}–{fmt(to)} / {fmt(total)}
      </span>
      <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)} className={cn(btn, 'text-text2 hover:bg-soft')}>
        上一页
      </button>
      {nums.map((n, i) =>
        n === '…' ? (
          <span key={`e${i}`} className="px-1 text-[11.5px] text-muted">
            …
          </span>
        ) : (
          <button key={n} type="button" aria-current={n === page ? 'page' : undefined} onClick={() => onChange(n)} className={cn(btn, n === page ? 'bg-active font-medium text-ink' : 'text-text2 hover:bg-soft')}>
            {n}
          </button>
        ),
      )}
      <button type="button" disabled={page >= pages} onClick={() => onChange(page + 1)} className={cn(btn, 'text-text2 hover:bg-soft')}>
        下一页
      </button>
    </nav>
  );
}

/** 千分位整数 */
export const fmt = (n: number) => n.toLocaleString('en-US');

/** Token 等大数：1.28M / 86K */
export function compact(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

/** 后端时间（ISO，无时区，Asia/Shanghai）→ 今天 14:31 / 昨天 22:14 / 09-26 10:02 / 2025-11-02 */
export function relTime(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return '—';
  const d = new Date(iso.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff === 0) return `今天 ${hm}`;
  if (diff === 1) return `昨天 ${hm}`;
  if (d.getFullYear() === now.getFullYear()) return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 表格表头单元格样式 */
export const th = 'pb-2.5 text-left text-[11px] font-normal text-muted';
export const td = 'py-[11px] text-[12px] text-text2';
