/** 模型管理纯函数：元数据解析、候选分组、错误提示 */
import { ApiError } from '@/api/http';

import type { SyncCandidate } from './api';

/** rawMetadata 可能是 JSON 字符串或已解析对象；解析失败时原样返回字符串 */
export function parseJsonish(v: unknown): unknown {
  if (typeof v !== 'string') return v ?? null;
  const s = v.trim();
  if (!s) return null;
  try {
    return JSON.parse(s);
  } catch {
    return v;
  }
}

/** 模态列表：数组 / JSON 字符串 / 逗号分隔字符串 → string[] */
export function parseModalities(v: unknown): string[] {
  const p = parseJsonish(v);
  if (Array.isArray(p)) return p.map(String).filter(Boolean);
  if (typeof p === 'string') return p.split(/[,，\s]+/).filter(Boolean);
  return [];
}

/** 元数据格式化为缩进 JSON 文本 */
export function prettyMetadata(v: unknown): string {
  const p = parseJsonish(v);
  if (p === null || p === undefined) return '';
  if (typeof p === 'string') return p;
  return JSON.stringify(p, null, 2);
}

export interface CandidateGroup {
  key: string;
  modelName: string;
  providerId: number;
  items: SyncCandidate[];
}

/** 按「厂商 + 模型名」分组（同一外部模型可能对应多种能力），组内按能力排序，组按最新出现时间倒序 */
export function groupCandidates(list: SyncCandidate[]): CandidateGroup[] {
  const map = new Map<string, CandidateGroup>();
  for (const c of list) {
    const key = `${c.providerId}:${c.modelName}`;
    let g = map.get(key);
    if (!g) {
      g = { key, modelName: c.modelName, providerId: c.providerId, items: [] };
      map.set(key, g);
    }
    g.items.push(c);
  }
  const latest = (g: CandidateGroup) => g.items.reduce((m, c) => (c.lastSeenAt > m ? c.lastSeenAt : m), '');
  const groups = [...map.values()];
  for (const g of groups) g.items.sort((a, b) => a.capability.localeCompare(b.capability));
  return groups.sort((a, b) => latest(b).localeCompare(latest(a)) || a.modelName.localeCompare(b.modelName));
}

/** 上下文长度：128000 → 128K */
export function tokens(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

export const errMsg = (e: unknown, fallback = '操作失败') => (e instanceof ApiError || e instanceof Error ? e.message || fallback : fallback);
export const isCode = (e: unknown, code: number) => e instanceof ApiError && Number(e.code) === code;

/** 同一厂商下按真实模型名分组（一个模型可有多种能力），保持首次出现顺序 */
export function groupByModelName<T extends { modelName: string }>(list: T[]): { modelName: string; items: T[] }[] {
  const map = new Map<string, T[]>();
  for (const m of list) {
    const arr = map.get(m.modelName);
    if (arr) arr.push(m);
    else map.set(m.modelName, [m]);
  }
  return [...map].map(([modelName, items]) => ({ modelName, items }));
}

/** 任务耗时：4.2s / 1m 12s；未结束返回 — */
export function duration(start: string, end: string | null): string {
  if (!end) return '—';
  const ms = new Date(end.replace(' ', 'T')).getTime() - new Date(start.replace(' ', 'T')).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}
