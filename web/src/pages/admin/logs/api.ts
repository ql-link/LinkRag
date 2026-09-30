/**
 * 日志追踪接口（/api/v1/admin/logs*，数据源 Loki）。
 *
 * - 查询参数为 snake_case：service / level / trace_id / keyword / start_time / end_time / page / page_size(≤200)；
 * - 时间以带时区的 ISO 字符串发送；不传时后端默认最近 24 小时；
 * - `total` 只是本次从 Loki 拉取到的行数（按 page*page_size 拉取，最多 1000 行），不是真实总数；
 * - Loki 不可达时返回 502。
 */
import { request, USE_MOCK, type Page } from '@/api/http';

import { mockLabels, mockQuery } from './mock';

export const LOG_LEVELS = ['TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL', 'ACCESS', 'AUDIT'] as const;
export const DEFAULT_SERVICES = ['tolink-rag', 'tolink-service'];

/** 后端单次最多从 Loki 拉取的行数：翻页不能超过这个窗口 */
export const LOKI_FETCH_CAP = 1000;

export interface LogEntry {
  /** ISO 时间（UTC 带偏移，或 loguru record 的本地时间 repr） */
  time: string;
  level: string | null;
  service: string | null;
  host: string | null;
  pid: string | null;
  trace_id: string | null;
  logger_name: string | null;
  message: string | null;
  exception: string | null;
  raw?: string | null;
}

export interface LogLabels {
  services: string[];
  levels: string[];
}

export interface LogQuery {
  service?: string;
  level?: string;
  traceId?: string;
  keyword?: string;
  start?: Date | string;
  end?: Date | string;
  page?: number;
  pageSize?: number;
}

const iso = (v: Date | string | undefined) => (v instanceof Date ? v.toISOString() : v || undefined);

/** 组装后端查询参数：去空值、裁剪空白、page_size 上限 200 */
export function buildLogQuery(p: LogQuery) {
  const trim = (s?: string) => s?.trim() || undefined;
  return {
    service: trim(p.service),
    level: trim(p.level)?.toUpperCase(),
    trace_id: trim(p.traceId),
    keyword: trim(p.keyword),
    start_time: iso(p.start),
    end_time: iso(p.end),
    page: Math.max(1, p.page ?? 1),
    page_size: Math.min(200, Math.max(1, p.pageSize ?? 50)),
  };
}

export const logsApi = {
  query: (params: LogQuery): Promise<Page<LogEntry>> =>
    USE_MOCK ? mockQuery(buildLogQuery(params)) : request<Page<LogEntry>>('/api/v1/admin/logs', { query: buildLogQuery(params) }),
  labels: (): Promise<LogLabels> => (USE_MOCK ? mockLabels() : request<LogLabels>('/api/v1/admin/logs/labels')),
};

/* ---------------- 时间范围 ---------------- */

export type LogRange = '2h' | '24h' | '7d';
export const RANGES: { value: LogRange; label: string; ms: number }[] = [
  { value: '2h', label: '最近 2 小时', ms: 2 * 3600_000 },
  { value: '24h', label: '最近 24 小时', ms: 24 * 3600_000 },
  { value: '7d', label: '最近 7 天', ms: 7 * 86_400_000 },
];

export const parseRange = (v: string | null): LogRange => (RANGES.some((r) => r.value === v) ? (v as LogRange) : '2h');

/** 相对时间范围 → 绝对起止时间（以 now 为终点） */
export function rangeWindow(range: LogRange, now: number = Date.now()) {
  const ms = RANGES.find((r) => r.value === range)!.ms;
  return { start: new Date(now - ms), end: new Date(now) };
}

/* ---------------- 时间格式 ---------------- */

/** 解析日志时间：兼容 `2026-09-29 14:32:08.412345+08:00` 这类 6 位小数 / 空格分隔的 repr */
export function parseLogTime(s: string | null | undefined): Date | null {
  if (!s) return null;
  const norm = s.trim().replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1');
  const d = new Date(norm);
  return Number.isNaN(d.getTime()) ? null : d;
}

const pad = (n: number, w = 2) => String(n).padStart(w, '0');
const md = (d: Date) => `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const hm = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const hms = (d: Date) => `${hm(d)}:${pad(d.getSeconds())}`;
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/** 列表时间列：当天显示 14:32:08.412，其他日期显示 09-28 14:32:08 */
export function fmtClock(s: string, now = new Date()) {
  const d = parseLogTime(s);
  if (!d) return s;
  return sameDay(d, now) ? `${hms(d)}.${pad(d.getMilliseconds(), 3)}` : `${md(d)} ${hms(d)}`;
}

/** 详情完整时间：2026-09-29 14:32:08.412 */
export function fmtFull(s: string) {
  const d = parseLogTime(s);
  return d ? `${d.getFullYear()}-${md(d)} ${hms(d)}.${pad(d.getMilliseconds(), 3)}` : s;
}

/** 时间范围展示：09-29 12:30 — 14:30（跨天时两端都带日期） */
export function fmtWindow(start: Date, end: Date) {
  return sameDay(start, end) ? `${md(start)} ${hm(start)} — ${hm(end)}` : `${md(start)} ${hm(start)} — ${md(end)} ${hm(end)}`;
}

/** 毫秒跨度：820ms / 3.3s / 2.1min */
export function fmtSpan(ms: number) {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}min`;
}
