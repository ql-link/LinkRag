/** 设计稿 E1–E3 日志追踪：Loki 集中日志检索、trace_id 链路追踪、日志详情 */
import { RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import type { Page } from '@/api/http';
import { cn } from '@/lib/cn';

import { AdminColumn } from '../AdminLayout';
import { actionBtn, StaleBanner, StateFeedback } from '../StateFeedback';
import { AdminHeader } from '../ui';
import { DEFAULT_SERVICES, logsApi, type LogEntry, type LogLabels } from './api';
import { DetailPanel } from './DetailPanel';
import { FiltersBar } from './FiltersBar';
import { LogTable } from './LogTable';
import { countLevels, EMPTY_FILTERS, filterCount, filtersFromSearch, filtersToSearch, maxPage, pageInfo, toQuery, type LogFilters } from './logic';
import { Pager } from './Pager';
import { Summary } from './Summary';
import { TraceTimeline } from './TraceTimeline';

const AUTO_REFRESH_MS = 10_000;

const errMsg = (e: unknown) => {
  const err = e as { status?: number; message?: string };
  if (err?.status === 502) return 'Loki 日志服务暂不可用';
  return err?.message || '加载失败';
};

export default function LogsPage() {
  const [sp, setSp] = useSearchParams();
  const applied = useMemo(() => filtersFromSearch(sp), [sp]);
  const [draft, setDraft] = useState<LogFilters>(applied);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [data, setData] = useState<Page<LogEntry> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [labels, setLabels] = useState<LogLabels | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [auto, setAuto] = useState(false);
  const seq = useRef(0);

  // URL 变化（深链、浏览器前进后退）时同步表单
  useEffect(() => setDraft(applied), [applied]);

  useEffect(() => {
    logsApi.labels().then(setLabels, () => setLabels(null));
  }, []);

  const load = useCallback(
    (opts?: { keepSelection?: boolean }) => {
      const id = ++seq.current;
      setLoading(true);
      logsApi
        .query(toQuery(applied, page, pageSize))
        .then((res) => {
          if (id !== seq.current) return;
          setData(res);
          setError(null);
          if (!opts?.keepSelection) setSelected(null);
        })
        .catch((e) => id === seq.current && setError(errMsg(e)))
        .finally(() => id === seq.current && setLoading(false));
    },
    [applied, page, pageSize],
  );
  useEffect(() => load(), [load]);

  // 自动刷新：详情打开时保留选中行
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(() => load({ keepSelection: true }), AUTO_REFRESH_MS);
    return () => clearInterval(t);
  }, [auto, load]);

  const apply = (f: LogFilters) => {
    setPage(1);
    setSp(filtersToSearch(f));
    // 筛选未变化时 setSp 不会触发重新加载，手动刷新
    if (filtersToSearch(f).toString() === filtersToSearch(applied).toString()) load();
  };
  const trace = (traceId: string) => apply({ ...applied, traceId });

  const items = data?.items ?? [];
  const levels = countLevels(items);
  const info = data ? pageInfo(data.total, page, pageSize) : null;
  const entry = selected !== null ? items[selected] : undefined;
  const services = labels?.services?.length ? labels.services : DEFAULT_SERVICES;

  return (
    <AdminColumn>
      <AdminHeader
        eyebrow="日志追踪 · Loki 集中日志"
        title="日志追踪"
        desc="按服务、级别、trace_id 和关键字检索 Java / Python 集中日志。"
        actions={
          <>
            <button type="button" aria-pressed={auto} onClick={() => setAuto((v) => !v)} className={cn(actionBtn, 'flex items-center gap-1.5 font-normal', auto && 'border-ink text-ink')}>
              {auto && <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-green" />}
              {auto ? `自动刷新 · ${AUTO_REFRESH_MS / 1000}s` : '自动刷新'}
            </button>
            <button type="button" onClick={() => load({ keepSelection: true })} disabled={loading} className={cn(actionBtn, 'flex items-center gap-1.5 font-normal disabled:opacity-60')}>
              <RefreshCw aria-hidden className={cn('size-3.5', loading && 'animate-spin')} />
              刷新
            </button>
          </>
        }
      />

      <FiltersBar value={draft} services={services} levels={labels?.levels} onChange={setDraft} onSubmit={() => apply(draft)} onReset={() => apply(EMPTY_FILTERS)} loading={loading} />

      {!data ? (
        error ? (
          <StateFeedback kind="error" size="page" title="日志加载失败" desc={error} action={<button type="button" onClick={() => load()} className={actionBtn}>重新加载</button>} />
        ) : (
          <StateFeedback kind="loading" size="page" title="正在查询日志" desc="Loki 检索范围较大时可能需要几秒钟" />
        )
      ) : (
        <>
          {error && <StaleBanner message={`刷新失败：${error}`} onRetry={() => load({ keepSelection: true })} />}
          <Summary total={info!.totalLabel} error={levels.error} warn={levels.warn} filters={filterCount(applied)} />
          {applied.traceId && items.length > 0 && <TraceTimeline traceId={applied.traceId} items={items} onSelect={setSelected} onClear={() => apply({ ...applied, traceId: '' })} />}
          {items.length === 0 ? (
            <StateFeedback
              kind="empty"
              size="card"
              title={page > 1 ? '这一页没有更多日志' : '没有匹配的日志'}
              desc={page > 1 ? '后端最多返回 1,000 条，已到达结果末尾。' : '试试放宽级别、清除关键字，或扩大时间范围。'}
              action={
                page > 1 ? (
                  <button type="button" onClick={() => setPage(1)} className={actionBtn}>回到第一页</button>
                ) : filterCount(applied) > 0 ? (
                  <button type="button" onClick={() => apply({ ...EMPTY_FILTERS, range: applied.range })} className={actionBtn}>清除筛选条件</button>
                ) : undefined
              }
            />
          ) : (
            <div className={cn('transition-opacity', loading && 'opacity-60')}>
              <LogTable items={items} selected={selected} onSelect={setSelected} onTrace={trace} activeTrace={applied.traceId} />
              <Pager
                page={page}
                pageSize={pageSize}
                total={data.total}
                shown={items.length}
                onPage={(p) => setPage(Math.min(maxPage(pageSize), Math.max(1, p)))}
                onPageSize={(n) => {
                  setPageSize(n);
                  setPage(1);
                }}
              />
            </div>
          )}
        </>
      )}

      {entry && (
        <DetailPanel
          entry={entry}
          rowNo={(page - 1) * pageSize + selected! + 1}
          onClose={() => setSelected(null)}
          onTrace={trace}
          onPrev={selected! > 0 ? () => setSelected(selected! - 1) : undefined}
          onNext={selected! < items.length - 1 ? () => setSelected(selected! + 1) : undefined}
        />
      )}
    </AdminColumn>
  );
}
