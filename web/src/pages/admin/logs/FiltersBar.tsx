/** 筛选行（设计稿 E1 Filters）：服务 / 级别 / trace_id / 关键字 / 时间范围 / 重置 / 查询 */
import { Calendar, RotateCcw, Search } from 'lucide-react';
import type { FormEvent } from 'react';

import { Button } from '@/components/ui/Button';

import { LOG_LEVELS, RANGES, fmtWindow, rangeWindow, type LogRange } from './api';
import { FilterSelect } from './FilterSelect';
import { LevelBadge } from './LevelBadge';
import type { LogFilters } from './logic';

interface Props {
  value: LogFilters;
  services: string[];
  levels?: string[];
  onChange: (next: LogFilters) => void;
  onSubmit: () => void;
  onReset: () => void;
  loading?: boolean;
}

const input =
  'h-8 w-full rounded-[7px] border border-line bg-white px-[11px] text-[12px] text-ink placeholder:text-muted transition-colors hover:border-faint focus:border-ink focus:outline-none';

export function FiltersBar({ value, services, levels, onChange, onSubmit, onReset, loading }: Props) {
  const set = <K extends keyof LogFilters>(k: K, v: LogFilters[K]) => onChange({ ...value, [k]: v });
  const win = rangeWindow(value.range);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit();
  };
  const levelList = levels?.length ? levels : [...LOG_LEVELS];

  return (
    <form role="search" aria-label="日志筛选" onSubmit={submit} className="flex flex-wrap items-end gap-3 pb-6">
      <FilterSelect
        label="服务"
        className="w-[150px]"
        num
        value={value.service}
        placeholder="不限定服务"
        options={[{ value: '', label: '不限定服务' }, ...services.map((s) => ({ value: s, label: s }))]}
        onChange={(v) => set('service', v)}
      />
      <FilterSelect
        label="级别"
        className="w-[110px]"
        width={150}
        value={value.level}
        placeholder="全部级别"
        options={[{ value: '', label: '全部级别' }, ...levelList.map((l) => ({ value: l, label: l, render: <LevelBadge level={l} /> }))]}
        onChange={(v) => set('level', v)}
      />
      <label className="flex w-[170px] flex-col gap-[5px]">
        <span className="text-[11px] text-muted">trace_id</span>
        <input className={`${input} font-mono text-[11.5px]`} placeholder="精确匹配" value={value.traceId} onChange={(e) => set('traceId', e.target.value)} spellCheck={false} />
      </label>
      <label className="flex w-[255px] flex-col gap-[5px]">
        <span className="text-[11px] text-muted">关键字</span>
        <span className="relative">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-[11px] size-3.5 -translate-y-1/2 text-muted" />
          <input className={`${input} pl-8`} placeholder="搜索 message / exception" value={value.keyword} onChange={(e) => set('keyword', e.target.value)} />
        </span>
      </label>
      <FilterSelect
        label="时间范围"
        className="w-[210px]"
        width={210}
        num
        icon={<Calendar />}
        value={value.range}
        options={RANGES.map((r) => ({ value: r.value, label: r.value === value.range ? fmtWindow(win.start, win.end) : r.label, render: <span>{r.label}</span> }))}
        onChange={(v) => set('range', v as LogRange)}
      />
      <button
        type="button"
        aria-label="重置筛选"
        title="重置筛选"
        onClick={onReset}
        className="flex size-8 items-center justify-center rounded-[7px] border border-line bg-white text-text2 transition-colors hover:bg-soft"
      >
        <RotateCcw aria-hidden className="size-3.5" />
      </button>
      <Button type="submit" disabled={loading} className="h-[30px] px-4 text-[12px]">
        查询
      </Button>
    </form>
  );
}
