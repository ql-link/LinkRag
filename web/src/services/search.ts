import { db } from '@/mock/db';
import { seedRecentSearches } from '@/mock/seed';
import type { ConversationSummary, Dataset, FileType, KbFile } from '@/types';

import { conversationSummaries } from './chat';
import { fileCount } from './datasets';

/**
 * 全局搜索服务（B3 / B4 / B5）。当前按名称 + Mock 内容片段在前端匹配；
 * 接入 Java 检索接口时只需替换本文件实现，页面只依赖这里导出的函数与类型。
 */

export const QUERY_MAX = 800;

export type SearchScope = 'all' | 'file' | 'conversation' | 'dataset';
export type SearchSort = 'relevance' | 'recent';
export type SearchTime = 'any' | '7d' | '30d';

export interface SearchFilters {
  datasetId?: string;
  type?: FileType;
  time: SearchTime;
  sort: SearchSort;
}

export interface FileHit {
  file: KbFile;
  dataset: Dataset;
  /** 命中位置：标题 / 内容 */
  titleHit: boolean;
  contentHits: number;
  snippet: string;
  /** 内容命中的页码与片段（⌘K 预览） */
  passages: { page: number; text: string }[];
  score: number;
}

export interface ConversationHit {
  conversation: ConversationSummary;
  dataset?: Dataset;
  score: number;
}

export interface DatasetHit {
  dataset: Dataset;
  files: number;
  score: number;
}

export interface SearchResult {
  query: string;
  files: FileHit[];
  conversations: ConversationHit[];
  datasets: DatasetHit[];
  summary?: SearchSummary;
}

export interface SearchSummary {
  text: string;
  datasetCount: number;
  chunkCount: number;
  model: string;
  citations: { index: number; title: string }[];
}

/** Mock 的文件正文片段：用于内容命中与摘要（设计稿中出现的内容） */
const passages: Record<string, { page: number; text: string }[]> = {
  f_002: [
    { page: 3, text: '第 3 节「Q3 路线图」共 12 项，按 P0 / P1 排序，优先级最高的是知识库多模态解析。' },
    { page: 5, text: '路线图第 2 项「对话引用溯源」计划 9 月 30 日上线。' },
    { page: 8, text: '团队空间权限排在路线图第 3 位，预计 10 月底完成。' },
  ],
  f_011: [{ page: 1, text: '评审结论：路线图第 2 项提前至 9 月 30 日上线。' }],
  f_m01: [{ page: 1, text: '年度路线图总览，含四个季度的关键里程碑。' }],
  f_t02: [{ page: 1, text: '存储层重构与检索性能优化的技术路线图。' }],
  f_004: [
    { page: 3, text: '主要竞品在知识库解析上已支持扫描件，我们的差距集中在表格与图片的结构化抽取。' },
    { page: 11, text: '竞品定价：团队版 ¥49/人/月，按 Token 超额计费，企业版需单独询价。' },
    { page: 14, text: '竞品 A 的检索召回在长文档场景下表现更稳定。' },
    { page: 19, text: '竞品 B 已开放 API，支持私有化部署。' },
    { page: 23, text: '三家竞品均提供引用溯源，但只有一家能定位到页码。' },
    { page: 30, text: '竞品的对话体验差异主要体现在多轮追问与引用展示。' },
  ],
  f_001: [{ page: 12, text: '新增扫描件 OCR 管线与图片语义理解，目标 10 月中旬灰度。' }],
  f_t01: [{ page: 2, text: 'API 鉴权使用 Bearer Token，过期后通过 refresh_token 换取新令牌。' }],
};

const pageTotals: Record<string, number> = { f_004: 42, f_002: 18, f_001: 32 };

export function passagesOf(fileId: string) {
  return passages[fileId] ?? [];
}

export function pageTotalOf(file: KbFile) {
  return pageTotals[file.id] ?? Math.max(3, Math.ceil(file.chunkCount / 2.7));
}

const norm = (s: string) => s.trim().toLowerCase();
const includes = (text: string, q: string) => text.toLowerCase().includes(q);
const countIn = (text: string, q: string) => text.toLowerCase().split(q).length - 1;

/** 设计稿中的日期（今天 / 昨天 / MM-DD / N 分钟前）换算为距今天数，用于时间筛选与排序 */
export function daysAgo(label: string): number {
  if (/分钟|小时|刚刚|今天/.test(label)) return 0;
  if (label.includes('昨天')) return 1;
  const m = label.match(/(\d{2})-(\d{2})/);
  if (!m) return 999;
  const today = new Date(2026, 8, 28);
  const d = new Date(2026, Number(m[1]) - 1, Number(m[2]));
  return Math.max(0, Math.round((today.getTime() - d.getTime()) / 86400000));
}

const withinTime = (label: string, t: SearchTime) => t === 'any' || daysAgo(label) <= (t === '7d' ? 7 : 30);

export function search(rawQuery: string, filters: SearchFilters = { time: 'any', sort: 'relevance' }): SearchResult {
  const query = rawQuery.trim().slice(0, QUERY_MAX);
  const q = norm(query);
  const { datasets, files: allFiles } = db.state;
  const dsById = new Map(datasets.map((d) => [d.id, d]));
  if (!q) return { query, files: [], conversations: [], datasets: [] };

  const files: FileHit[] = [];
  for (const file of allFiles) {
    const dataset = dsById.get(file.datasetId);
    if (!dataset) continue;
    if (filters.datasetId && file.datasetId !== filters.datasetId) continue;
    if (filters.type && file.type !== filters.type) continue;
    if (!withinTime(file.updatedAt, filters.time)) continue;
    const titleHit = includes(file.name, q);
    const ps = passagesOf(file.id).filter((p) => includes(p.text, q));
    const contentHits = ps.reduce((n, p) => n + countIn(p.text, q), 0);
    if (!titleHit && !contentHits) continue;
    files.push({
      file,
      dataset,
      titleHit,
      contentHits,
      passages: ps,
      snippet: ps[0]?.text ?? '',
      score: (titleHit ? 10 : 0) + contentHits * 3,
    });
  }

  const conversations: ConversationHit[] = conversationSummaries()
    .filter((c) => !filters.datasetId || c.datasetId === filters.datasetId)
    .filter((c) => withinTime(c.updatedAt, filters.time))
    .filter((c) => includes(c.title, q) || includes(c.lastQuestion, q))
    .map((c) => ({ conversation: c, dataset: dsById.get(c.datasetId), score: includes(c.title, q) ? 10 : 2 }));

  /** 名称 / 描述命中，或库内有文件命中 */
  const fileHitDs = new Set(files.map((f) => f.dataset.id));
  const dsHits: DatasetHit[] = datasets
    .filter((d) => !filters.datasetId || d.id === filters.datasetId)
    .filter((d) => includes(d.name, q) || includes(d.description, q) || fileHitDs.has(d.id))
    .map((d) => ({ dataset: d, files: fileCount(d.id), score: (includes(d.name, q) ? 10 : 0) + (includes(d.description, q) ? 4 : 0) + (fileHitDs.has(d.id) ? 1 : 0) }));

  const byScore = <T extends { score: number }>(a: T, b: T) => b.score - a.score;
  if (filters.sort === 'recent') {
    files.sort((a, b) => daysAgo(a.file.updatedAt) - daysAgo(b.file.updatedAt));
    conversations.sort((a, b) => daysAgo(a.conversation.updatedAt) - daysAgo(b.conversation.updatedAt));
  } else {
    /** 相关度相同时按更新时间 */
    files.sort((a, b) => byScore(a, b) || daysAgo(a.file.updatedAt) - daysAgo(b.file.updatedAt));
    conversations.sort((a, b) => byScore(a, b) || daysAgo(a.conversation.updatedAt) - daysAgo(b.conversation.updatedAt));
  }
  dsHits.sort(byScore);

  return { query, files, conversations, datasets: dsHits, summary: summarize(query, files) };
}

/** Mock 的 AI 回答：已知问题使用设计稿文案，其余拼接命中片段 */
const cannedAnswers: Record<string, string> = {
  路线图:
    '本季度路线图共 12 项，优先级最高的三项为：知识库多模态解析（10 月 15 日灰度）、对话引用溯源（9 月 30 日上线）与团队空间权限（10 月底）。其中引用溯源已进入联调阶段。',
};

/** 命中文件内容时才生成摘要，引用前两个来源 */
function summarize(query: string, files: FileHit[]): SearchSummary | undefined {
  const withContent = files.filter((f) => f.contentHits > 0);
  if (!withContent.length) return undefined;
  const shortName = (name: string) => name.replace(/\.[a-z]+$/i, '');
  return {
    text: cannedAnswers[query] ?? withContent.slice(0, 2).map((f) => f.passages[0].text).join(''),
    datasetCount: new Set(withContent.map((f) => f.dataset.id)).size,
    chunkCount: withContent.reduce((n, f) => n + f.passages.length, 0),
    model: 'DeepSeek-V3',
    citations: withContent.slice(0, 2).map((f, i) => ({ index: i + 1, title: shortName(f.file.name) })),
  };
}

/** 文件命中方式的展示文案 */
export function hitLabel(hit: FileHit): string {
  if (hit.contentHits > 1 || (!hit.titleHit && hit.contentHits)) return `内容命中 ${hit.contentHits} 处`;
  return '标题命中';
}

/** 无结果时「你可能在找」：最近对话 + 最近文件 */
export function suggestions() {
  const conv = conversationSummaries()[0];
  const file = db.state.files.find((f) => f.id === 'f_001') ?? db.state.files[0];
  return { conversation: conv, file, dataset: file ? db.state.datasets.find((d) => d.id === file.datasetId) : undefined };
}

/* ---------------- 最近搜索（本地存储） ---------------- */

const RECENT_KEY = 'linkrag.recentSearches';

export function recentSearches(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [...seedRecentSearches];
  } catch {
    return [...seedRecentSearches];
  }
}

export function pushRecentSearch(q: string) {
  const v = q.trim();
  if (!v) return;
  const next = [v, ...recentSearches().filter((s) => s !== v)].slice(0, 6);
  localStorage.setItem(RECENT_KEY, JSON.stringify(next));
}

export function clearRecentSearches() {
  localStorage.setItem(RECENT_KEY, '[]');
}

/** 将文本按关键词切分，供高亮渲染（大小写不敏感） */
export function splitHighlight(text: string, query: string): { text: string; hit: boolean }[] {
  const q = query.trim();
  if (!q) return [{ text, hit: false }];
  const out: { text: string; hit: boolean }[] = [];
  const lower = text.toLowerCase();
  const lq = q.toLowerCase();
  let i = 0;
  while (i < text.length) {
    const j = lower.indexOf(lq, i);
    if (j < 0) {
      out.push({ text: text.slice(i), hit: false });
      break;
    }
    if (j > i) out.push({ text: text.slice(i, j), hit: false });
    out.push({ text: text.slice(j, j + q.length), hit: true });
    i = j + q.length;
  }
  return out;
}

/* ---------------- 最近访问（⌘K 空关键词） ---------------- */

export type RecentVisit =
  | { kind: 'file'; file: KbFile; dataset: Dataset; at: string }
  | { kind: 'dataset'; dataset: Dataset; files: number; at: string }
  | { kind: 'conversation'; conversation: ConversationSummary; dataset?: Dataset; at: string };

/** 最近打开过的文件 / 知识库 / 对话；真实环境由后端按用户访问记录返回 */
export function recentVisits(): RecentVisit[] {
  const { files, datasets } = db.state;
  const out: RecentVisit[] = [];
  const file = files.find((f) => f.id === 'f_001');
  const fileDs = file && datasets.find((d) => d.id === file.datasetId);
  if (file && fileDs) out.push({ kind: 'file', file, dataset: fileDs, at: file.updatedAt });
  const ds = datasets.find((d) => d.id === 'ds_2c81e04a');
  if (ds) out.push({ kind: 'dataset', dataset: ds, files: fileCount(ds.id), at: '昨天' });
  const conv = conversationSummaries()[0];
  if (conv) out.push({ kind: 'conversation', conversation: conv, dataset: datasets.find((d) => d.id === conv.datasetId), at: conv.updatedAt });
  return out;
}
