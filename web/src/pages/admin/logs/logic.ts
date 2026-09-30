/** 日志追踪页纯逻辑：URL 深链 ↔ 筛选条件、分页窗口（1000 行上限）、级别配色 */
import type { Tone } from '@/components/ui/Chip';

import { LOKI_FETCH_CAP, parseRange, rangeWindow, type LogQuery, type LogRange } from './api';

export interface LogFilters {
  service: string;
  level: string;
  traceId: string;
  keyword: string;
  range: LogRange;
}

export const EMPTY_FILTERS: LogFilters = { service: '', level: '', traceId: '', keyword: '', range: '2h' };

/** 深链：?service= &level= &trace_id= &keyword= &range=2h|24h|7d */
export function filtersFromSearch(sp: URLSearchParams): LogFilters {
  return {
    service: sp.get('service')?.trim() ?? '',
    level: sp.get('level')?.trim().toUpperCase() ?? '',
    traceId: sp.get('trace_id')?.trim() ?? '',
    keyword: sp.get('keyword')?.trim() ?? '',
    range: parseRange(sp.get('range')),
  };
}

export function filtersToSearch(f: LogFilters): URLSearchParams {
  const sp = new URLSearchParams();
  if (f.service) sp.set('service', f.service);
  if (f.level) sp.set('level', f.level);
  if (f.traceId.trim()) sp.set('trace_id', f.traceId.trim());
  if (f.keyword.trim()) sp.set('keyword', f.keyword.trim());
  if (f.range !== '2h') sp.set('range', f.range);
  return sp;
}

/** 生效的筛选项数量（时间范围不计入） */
export const filterCount = (f: LogFilters) => [f.service, f.level, f.traceId.trim(), f.keyword.trim()].filter(Boolean).length;

/** 筛选条件 + 页码 → logsApi.query 参数；时间窗口以 now 为终点重新计算 */
export function toQuery(f: LogFilters, page: number, pageSize: number, now = Date.now()): LogQuery {
  const { start, end } = rangeWindow(f.range, now);
  return { service: f.service, level: f.level, traceId: f.traceId, keyword: f.keyword, start, end, page, pageSize };
}

/** 页码上限：后端最多拉取 1000 行，翻页不能越过该窗口 */
export const maxPage = (pageSize: number) => Math.max(1, Math.floor(LOKI_FETCH_CAP / pageSize));

/**
 * 分页信息。后端 total 只是本次拉取的行数（≤ page*pageSize 且 ≤ 1000）：
 * - total 恰好等于 page*pageSize 时后面可能还有，展示为「≥ N」并允许下一页；
 * - 达到 1000 时展示「1,000+」，并提示缩小范围。
 */
export function pageInfo(total: number, page: number, pageSize: number) {
  const capped = total >= LOKI_FETCH_CAP;
  const maybeMore = !capped && total >= page * pageSize;
  const hasNext = page < maxPage(pageSize) && total >= page * pageSize;
  const knownPages = Math.max(1, Math.ceil(Math.min(total, LOKI_FETCH_CAP) / pageSize));
  const fmt = (n: number) => n.toLocaleString('en-US');
  const totalLabel = capped ? `${fmt(LOKI_FETCH_CAP)}+` : maybeMore ? `≥ ${fmt(total)}` : fmt(total);
  return { capped, hasNext, hasPrev: page > 1, knownPages, totalLabel, exact: !capped && !maybeMore };
}

const LEVEL_TONE: Record<string, Tone> = {
  FATAL: 'red',
  ERROR: 'red',
  WARN: 'amber',
  WARNING: 'amber',
  INFO: 'blue',
  ACCESS: 'green',
  AUDIT: 'green',
};
export const levelTone = (level: string | null | undefined): Tone => LEVEL_TONE[(level ?? '').toUpperCase()] ?? 'gray';

/** 统计当前页各级别条数（WARNING 归入 WARN、FATAL 归入 ERROR） */
export function countLevels(items: { level: string | null }[]) {
  let error = 0;
  let warn = 0;
  for (const it of items) {
    const l = (it.level ?? '').toUpperCase();
    if (l === 'ERROR' || l === 'FATAL') error += 1;
    else if (l === 'WARN' || l === 'WARNING') warn += 1;
  }
  return { error, warn };
}
