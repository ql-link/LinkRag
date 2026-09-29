import { usageApi, type UsageLogDTO } from '@/api/endpoints';
import { USE_MOCK } from '@/api/http';
import { delay } from '@/mock/db';

/**
 * 用量（E1–E3）。Mock 模式按日生成确定性的调用数据；真实模式对接 Python
 * `/api/v1/llm/usage/{summary,daily,by-model,trend,logs}`，映射为同一 UsageReport 结构。
 */

const localToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

/** 「今天」：Mock 固定为设计稿日期；真实模式为本地当天。Mock 数据从 DATA_START 开始，更早的周期为空（E3） */
export const TODAY = USE_MOCK ? '2026-09-28' : localToday();
export const DATA_START = '2026-07-01';

export type Preset = 'today' | '7d' | '30d' | 'month' | 'lastMonth' | 'custom';
export interface DateRange {
  from: string;
  to: string;
}

export const presetLabel: Record<Preset, string> = {
  today: '今天',
  '7d': '近 7 天',
  '30d': '近 30 天',
  month: '本月',
  lastMonth: '上个月',
  custom: '自定义',
};
export const PRESETS: Preset[] = ['today', '7d', '30d', 'month', 'lastMonth', 'custom'];

// ---------- 日期工具（统一用 UTC，避免时区偏移） ----------

const toDate = (iso: string) => new Date(`${iso}T00:00:00Z`);
const toIso = (d: Date) => d.toISOString().slice(0, 10);
export const addDays = (iso: string, n: number) => toIso(new Date(toDate(iso).getTime() + n * 86_400_000));
export const diffDays = (a: string, b: string) => Math.round((toDate(b).getTime() - toDate(a).getTime()) / 86_400_000);
export const monthStart = (iso: string) => `${iso.slice(0, 7)}-01`;
export const monthEnd = (iso: string) => {
  const d = toDate(monthStart(iso));
  d.setUTCMonth(d.getUTCMonth() + 1);
  return addDays(toIso(d), -1);
};

/** 解析 8 位日期（20260921）；非法返回 undefined */
export function parseCompactDate(s: string): string | undefined {
  if (!/^\d{8}$/.test(s)) return undefined;
  const iso = `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  const d = toDate(iso);
  return !Number.isNaN(d.getTime()) && toIso(d) === iso ? iso : undefined;
}

/**
 * 近 N 天：Mock 模式不含今天（与设计稿 09-21 — 09-27 一致）；
 * 真实模式包含今天，刚发生的对话 / 解析能立即在用量中看到。
 */
export function presetRange(p: Exclude<Preset, 'custom'>, today = TODAY): DateRange {
  const end = USE_MOCK ? -1 : 0;
  switch (p) {
    case 'today':
      return { from: today, to: today };
    case '7d':
      return { from: addDays(today, end - 6), to: addDays(today, end) };
    case '30d':
      return { from: addDays(today, end - 29), to: addDays(today, end) };
    case 'month':
      return { from: monthStart(today), to: today };
    case 'lastMonth': {
      const end = addDays(monthStart(today), -1);
      return { from: monthStart(end), to: end };
    }
  }
}

export function detectPreset(r: DateRange): Preset {
  return (PRESETS.filter((p) => p !== 'custom') as Exclude<Preset, 'custom'>[]).find((p) => {
    const x = presetRange(p);
    return x.from === r.from && x.to === r.to;
  }) ?? 'custom';
}

/** 2026-09-21 — 09-27；跨年时结束日期带年份 */
export function formatRange({ from, to }: DateRange) {
  if (from === to) return from;
  return `${from} — ${from.slice(0, 4) === to.slice(0, 4) ? to.slice(5) : to}`;
}

// ---------- 按日数据 ----------

interface Day {
  date: string;
  tokens: number;
  calls: number;
  failed: number;
  latency: number;
}

/** 设计稿对应的两周：09-21 — 09-27 为当前周期，09-14 — 09-20 为上一周期（环比 +18.4% / +9.2%） */
const designed: Record<string, [tokens: number, calls: number, latency: number]> = {
  '2026-09-14': [142_300, 372, 1.9],
  '2026-09-15': [158_640, 418, 1.9],
  '2026-09-16': [150_110, 405, 1.9],
  '2026-09-17': [171_900, 446, 1.9],
  '2026-09-18': [163_284, 433, 1.9],
  '2026-09-19': [139_200, 379, 1.9],
  '2026-09-20': [159_500, 428, 1.9],
  '2026-09-21': [128_640, 318, 1.84],
  '2026-09-22': [151_020, 372, 1.84],
  '2026-09-23': [141_700, 351, 1.84],
  '2026-09-24': [195_810, 486, 1.84],
  '2026-09-25': [173_440, 428, 1.84],
  '2026-09-26': [232_952, 563, 1.84],
  '2026-09-27': [261_000, 628, 1.84],
};

/** 以日期为种子的伪随机数，保证每次渲染一致 */
function rng(seed: string) {
  let h = 2166136261;
  for (const c of seed) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

const INPUT_RATIO = 0.7648;
const FAIL_RATIO = 0.008;

function day(date: string): Day | undefined {
  if (date < DATA_START || date > TODAY) return undefined;
  const fixed = designed[date];
  let tokens: number, calls: number, latency: number;
  if (fixed) [tokens, calls, latency] = fixed;
  else {
    const r = rng(date);
    const weekend = [0, 6].includes(toDate(date).getUTCDay());
    calls = Math.round((weekend ? 180 : 330) + r() * 160);
    // 今天只统计到当前时刻
    if (date === TODAY) calls = Math.round(calls * 0.62);
    tokens = Math.round(calls * (380 + r() * 60));
    latency = Math.round((1.6 + r() * 0.5) * 100) / 100;
  }
  return { date, tokens, calls, failed: Math.round(calls * FAIL_RATIO), latency };
}

const daysIn = ({ from, to }: DateRange) =>
  Array.from({ length: diffDays(from, to) + 1 }, (_, i) => day(addDays(from, i))).filter((d): d is Day => !!d);

// ---------- 调用记录 ----------

export type CallStatus = 'ok' | 'timeout' | 'quota';
export interface CallRecord {
  id: string;
  /** YYYY-MM-DD HH:mm:ss */
  time: string;
  model: string;
  scene: string;
  tokens: number;
  latency: number;
  status: CallStatus;
}

const templates: { model: string; scenes: string[]; tokens: [number, number]; latency: [number, number] }[] = [
  { model: 'DeepSeek-V3', scenes: ['对话 · 产品知识库', '对话 · 技术文档库', '对话 · 客服话术库'], tokens: [1800, 5200], latency: [1.4, 2.8] },
  { model: 'Qwen-Max', scenes: ['对话 · 人事制度库', '对话 · 市场调研库'], tokens: [1500, 4600], latency: [1.2, 2.6] },
  { model: 'bge-m3', scenes: ['向量检索', '文件解析 · 向量化'], tokens: [200, 900], latency: [0.1, 0.4] },
  { model: 'Qwen-VL-Max', scenes: ['OCR 解析'], tokens: [5000, 9800], latency: [4, 7] },
  { model: 'bge-reranker-v2', scenes: ['检索重排'], tokens: [300, 1200], latency: [0.15, 0.5] },
  { model: 'Paraformer-v2', scenes: ['语音转写'], tokens: [800, 3000], latency: [2, 5] },
];

/** 设计稿 E1 中 09-27 最近的 5 条调用 */
const designedCalls: Omit<CallRecord, 'id'>[] = [
  { time: '2026-09-27 14:32:08', model: 'DeepSeek-V3', scene: '对话 · 产品知识库', tokens: 4812, latency: 2.41, status: 'ok' },
  { time: '2026-09-27 14:31:55', model: 'bge-m3', scene: '向量检索', tokens: 512, latency: 0.18, status: 'ok' },
  { time: '2026-09-27 14:20:11', model: 'Qwen-VL-Max', scene: 'OCR 解析', tokens: 9204, latency: 6.02, status: 'timeout' },
  { time: '2026-09-27 14:18:47', model: 'DeepSeek-V3', scene: '对话 · 技术文档库', tokens: 3377, latency: 1.92, status: 'ok' },
  { time: '2026-09-27 13:59:02', model: 'Qwen-Max', scene: '对话 · 人事制度库', tokens: 0, latency: 0.31, status: 'quota' },
];

const pad = (n: number) => String(n).padStart(2, '0');
const clock = (sec: number) => `${pad(Math.floor(sec / 3600))}:${pad(Math.floor(sec / 60) % 60)}:${pad(sec % 60)}`;

/** 某天的调用记录，按时间倒序 */
function callsOf(d: Day): CallRecord[] {
  const r = rng(`${d.date}#calls`);
  const head = d.date === '2026-09-27' ? designedCalls : [];
  const latestSec = head.length ? 13 * 3600 + 58 * 60 : d.date === TODAY ? 15 * 3600 + 10 * 60 : 22 * 3600 + r() * 5400;
  const count = d.calls - head.length;
  const failedAt = new Set(Array.from({ length: Math.max(0, d.failed - head.filter((c) => c.status !== 'ok').length) }, () => Math.floor(r() * count)));
  const step = (latestSec - 8 * 3600 * r()) / Math.max(1, count);
  const rest = Array.from({ length: count }, (_, i): Omit<CallRecord, 'id'> => {
    const t = templates[Math.floor(r() * r() * templates.length)];
    const status: CallStatus = failedAt.has(i) ? (r() < 0.6 ? 'timeout' : 'quota') : 'ok';
    const tokens = Math.round(t.tokens[0] + r() * (t.tokens[1] - t.tokens[0]));
    return {
      time: `${d.date} ${clock(Math.max(0, Math.round(latestSec - i * step - r() * step * 0.8)))}`,
      model: t.model,
      scene: t.scenes[Math.floor(r() * t.scenes.length)],
      tokens: status === 'quota' ? 0 : tokens,
      latency: Math.round((t.latency[0] + r() * (t.latency[1] - t.latency[0])) * 100) / 100,
      status,
    };
  });
  return [...head, ...rest].map((c, i) => ({ ...c, id: `${d.date}-${i}` }));
}

// ---------- 报表 ----------

export interface ModelShare {
  name: string;
  share: number;
  color: string;
}
export interface TrendPoint {
  label: string;
  from: string;
  tokens: number;
}
export interface UsageReport {
  range: DateRange;
  empty: boolean;
  totals: { tokens: number; calls: number; input: number; output: number; successRate: number | null; avgLatency: number | null };
  /** 与上一等长周期相比的变化比例；上一周期无数据时为 null */
  change: { tokens: number; calls: number } | null;
  granularity: 'day' | 'week';
  trend: TrendPoint[];
  models: ModelShare[];
  recentTotal: number;
}

/** 模型占比（Mock 固定比例，真实环境由后端聚合） */
const modelShares: ModelShare[] = [
  { name: 'DeepSeek-V3', share: 0.52, color: 'var(--color-blue)' },
  { name: 'Qwen-Max', share: 0.24, color: 'var(--color-purple)' },
  { name: 'bge-m3 向量', share: 0.16, color: 'var(--color-green)' },
  { name: '其他模型', share: 0.08, color: 'var(--color-dash)' },
];

function totalsOf(days: Day[]) {
  const tokens = days.reduce((s, d) => s + d.tokens, 0);
  const calls = days.reduce((s, d) => s + d.calls, 0);
  const failed = days.reduce((s, d) => s + d.failed, 0);
  const input = days.reduce((s, d) => s + Math.round(d.tokens * INPUT_RATIO), 0);
  return {
    tokens,
    calls,
    input,
    output: tokens - input,
    successRate: calls ? (calls - failed) / calls : null,
    avgLatency: calls ? days.reduce((s, d) => s + d.latency * d.calls, 0) / calls : null,
  };
}

/** 超过 31 天按周聚合，避免柱子过密 */
function trendOf(range: DateRange, days: Day[]): Pick<UsageReport, 'granularity' | 'trend'> {
  const len = diffDays(range.from, range.to) + 1;
  const byDate = new Map(days.map((d) => [d.date, d.tokens]));
  if (len <= 31) {
    return {
      granularity: 'day',
      trend: Array.from({ length: len }, (_, i) => {
        const date = addDays(range.from, i);
        return { label: date.slice(5), from: date, tokens: byDate.get(date) ?? 0 };
      }),
    };
  }
  return {
    granularity: 'week',
    trend: Array.from({ length: Math.ceil(len / 7) }, (_, w) => {
      const from = addDays(range.from, w * 7);
      const tokens = Array.from({ length: 7 }, (_, i) => byDate.get(addDays(from, i)) ?? 0).reduce((a, b) => a + b, 0);
      return { label: from.slice(5), from, tokens };
    }),
  };
}

export function usageReport(range: DateRange): UsageReport {
  const days = daysIn(range);
  const totals = totalsOf(days);
  const len = diffDays(range.from, range.to) + 1;
  const prev = totalsOf(daysIn({ from: addDays(range.from, -len), to: addDays(range.from, -1) }));
  return {
    range,
    empty: totals.calls === 0,
    totals,
    change: prev.calls ? { tokens: totals.tokens / prev.tokens - 1, calls: totals.calls / prev.calls - 1 } : null,
    ...trendOf(range, days),
    models: totals.calls ? modelShares : [],
    recentTotal: totals.calls,
  };
}

const PALETTE = ['var(--color-blue)', 'var(--color-purple)', 'var(--color-green)', 'var(--color-amber)'];

/** 真实模式下已加载的调用日志（recentCalls 同步读取；loadMoreCalls 追加） */
let logCache: { key: string; rows: CallRecord[]; total: number } = { key: '', rows: [], total: 0 };
const rangeKey = (r: DateRange) => `${r.from}~${r.to}`;

function toCall(l: UsageLogDTO): CallRecord {
  const t = l.createdAt.replace('T', ' ').slice(0, 19);
  const scene = { chat: '对话', parse: '文件解析', recall: '检索', embedding: '向量化' }[l.stage] ?? l.stage;
  const failed = l.status !== 'success';
  return {
    id: String(l.id),
    time: t,
    model: l.modelName,
    scene: `${scene}${l.operation ? ` · ${l.operation}` : ''}`,
    tokens: l.totalTokens,
    latency: (l.latencyMs ?? 0) / 1000,
    status: !failed ? 'ok' : /quota|额度|429/i.test(l.errorMessage ?? '') ? 'quota' : 'timeout',
  };
}

async function remoteReport(range: DateRange): Promise<UsageReport> {
  const q = { startDate: range.from, endDate: range.to, stage: 'all' };
  const [summary, daily, byModel, trend, logs] = await Promise.all([
    usageApi.summary(q),
    usageApi.daily(q),
    usageApi.byModel(q),
    usageApi.trend(q),
    usageApi.logs(q, 1, 20),
  ]);
  logCache = { key: rangeKey(range), rows: logs.items.map(toCall), total: logs.total };
  const days: Day[] = daily.map((d) => ({ date: d.date, tokens: d.totalTokens, calls: d.calls, failed: 0, latency: 0 }));
  const totalTokens = byModel.reduce((n, m) => n + m.totalTokens, 0) || 1;
  const sorted = [...byModel].sort((a, b) => b.totalTokens - a.totalTokens);
  const top = sorted.slice(0, 3);
  const rest = sorted.slice(3).reduce((n, m) => n + m.totalTokens, 0);
  const models: ModelShare[] = [
    ...top.map((m, i) => ({ name: m.modelName, share: m.totalTokens / totalTokens, color: PALETTE[i] })),
    ...(rest ? [{ name: '其他模型', share: rest / totalTokens, color: 'var(--color-dash)' }] : []),
  ];
  return {
    range,
    empty: summary.totalCalls === 0,
    totals: {
      tokens: summary.totalTokens,
      calls: summary.totalCalls,
      input: summary.promptTokens,
      output: summary.completionTokens,
      successRate: summary.totalCalls ? (summary.successRate ?? summary.successCalls / summary.totalCalls) : null,
      avgLatency: summary.averageLatencyMs != null ? summary.averageLatencyMs / 1000 : null,
    },
    change:
      trend.previousCalls && trend.tokenGrowthRate != null && trend.callGrowthRate != null
        ? { tokens: trend.tokenGrowthRate, calls: trend.callGrowthRate }
        : null,
    ...trendOf(range, days),
    models: summary.totalCalls ? models : [],
    recentTotal: logs.total,
  };
}

export async function getUsage(range: DateRange): Promise<UsageReport> {
  if (!USE_MOCK) return remoteReport(range);
  await delay(220);
  return usageReport(range);
}

/** 真实模式：「加载更多」时拉取下一页日志；Mock 模式无需请求，返回 undefined */
export function loadMoreCalls(range: DateRange, limit: number): Promise<void> | undefined {
  if (USE_MOCK) return undefined;
  return fetchMoreCalls(range, limit);
}

async function fetchMoreCalls(range: DateRange, limit: number) {
  if (logCache.key !== rangeKey(range) || logCache.rows.length >= limit) return;
  const q = { startDate: range.from, endDate: range.to, stage: 'all' };
  const pageSize = 20;
  while (logCache.rows.length < Math.min(limit, logCache.total)) {
    const page = Math.floor(logCache.rows.length / pageSize) + 1;
    const res = await usageApi.logs(q, page, pageSize);
    if (!res.items.length) break;
    logCache = { ...logCache, rows: [...logCache.rows, ...res.items.map(toCall)].slice(0, page * pageSize), total: res.total };
  }
}

/** 最近调用，按时间倒序分页；只生成需要的天数 */
export function recentCalls(range: DateRange, limit: number): CallRecord[] {
  if (!USE_MOCK) return logCache.key === rangeKey(range) ? logCache.rows.slice(0, limit) : [];
  const out: CallRecord[] = [];
  for (const d of daysIn(range).reverse()) {
    out.push(...callsOf(d).slice(0, limit - out.length));
    if (out.length >= limit) break;
  }
  return out;
}

// ---------- 展示格式 ----------

export const formatInt = (n: number) => n.toLocaleString('en-US');
export function formatCompact(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2).replace(/\.?0+$/, '')}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}K`;
  return String(n);
}
export const formatPercent = (r: number, digits = 1) => `${(r * 100).toFixed(digits)}%`;
