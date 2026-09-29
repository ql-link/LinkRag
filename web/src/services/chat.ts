import { useSyncExternalStore } from 'react';

import { USE_MOCK } from '@/api/http';
import { db, delay } from '@/mock/db';
import { seedConversations } from '@/mock/seed';
import type { ConversationSummary, FileType, KbFile } from '@/types';

import { createRemote } from './chatRemote';
import { findModel, modelStore } from './models';

/**
 * 对话服务（F1–F7）。Mock 模式下检索与生成由定时器模拟；真实模式（chatRemote.ts）对接
 * Python 会话接口与 /api/v1/rag/stream，流事件映射到同一套状态字段，页面组件不区分两种模式。
 */

export const QUESTION_MAX = 800;

/** 召回片段（右侧面板 + 原文预览） */
export interface RetrievedChunk {
  /** 回答中的编号：[片段 N] */
  n: number;
  fileId: string;
  fileName: string;
  fileType: FileType;
  datasetId: string;
  datasetName: string;
  /** 第 12 页 / 第 3 节 */
  location: string;
  section: string;
  score: number;
  tokens: number;
  /** 片段摘要（面板卡片） */
  text: string;
  /** 原文预览：命中段落前后的上下文 */
  before: string;
  after: string;
  /** 片段完整正文（真实模式；原文预览使用） */
  full?: string;
}

export type AnswerBlock = { kind: 'p'; text: string; cite?: number[] } | { kind: 'item'; n: number; title: string; text: string; cite?: number[] };

export type StepState = 'pending' | 'active' | 'done';
export interface ThinkingStep {
  key: 'understand' | 'retrieve' | 'generate';
  state: StepState;
  /** 完成耗时（秒） */
  elapsed?: number;
  detail?: string;
}

export type AssistantStatus = 'thinking' | 'streaming' | 'done' | 'stopped' | 'error';

export interface UserMessage {
  id: string;
  role: 'user';
  text: string;
}
export interface AssistantMessage {
  id: string;
  role: 'assistant';
  status: AssistantStatus;
  model: string;
  steps: ThinkingStep[];
  /** 进入「理解问题」的时间戳，用于实时计时 */
  startedAt: number;
  thinkingElapsed?: number;
  totalElapsed?: number;
  chunks: RetrievedChunk[];
  blocks: AnswerBlock[];
  /** 已流式输出的字符数；done 时等于全文长度 */
  shown: number;
  feedback?: 'up';
  error?: { message: string; requestId: string; at: string };
  /** 真实模式：本轮幂等键（停止生成用） */
  turnId?: string;
}
export type Message = UserMessage | AssistantMessage;

export interface Conversation {
  id: string;
  title: string;
  datasetIds: string[];
  model: string;
  pinned: boolean;
  updatedAt: string;
  messages: Message[];
  /** 真实模式：历史消息是否已加载 */
  loaded?: boolean;
  /** 真实模式：后端记录的最近一次对话模型配置（模型名无法匹配时兜底） */
  configId?: number;
}

interface ChatState {
  conversations: Conversation[];
}

const SNIPPETS = [
  '文档对该问题给出了明确的流程说明，关键节点需由负责人确认后执行',
  '相关条款在最新版本中做了调整，旧版本的描述已不再适用',
  '资料中列出了适用范围与例外情况，建议结合具体场景判断',
  '文中给出了示例与常见问题，可直接作为操作参考',
  '该部分由对应团队维护，最近一次更新在本月',
];

function hashOf(s: string) {
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

/* ---------------- store ---------------- */

const CITE_DESIGNED: Omit<RetrievedChunk, 'datasetName'>[] = [
  {
    n: 1,
    fileId: 'f_001',
    fileName: '产品需求文档_v3.2.pdf',
    fileType: 'PDF',
    datasetId: 'ds_7f3a91c2',
    location: '第 12 页',
    section: '第 3 章 多模态',
    score: 0.92,
    tokens: 412,
    text: '多模态解析：新增扫描件 OCR 管线与图片语义理解，目标 10 月中旬灰度…',
    before: '3.1 背景：当前知识库仅支持文本型 PDF，扫描件与图片内容无法被检索，用户反馈占比 23%。',
    after: '3.2 验收：扫描件识别准确率 ≥ 95%，单页解析耗时 ≤ 3s，图片描述支持中英文。',
  },
  {
    n: 2,
    fileId: 'f_011',
    fileName: '路线图评审纪要.md',
    fileType: 'MD',
    datasetId: 'ds_7f3a91c2',
    location: '第 1 节',
    section: '评审结论',
    score: 0.86,
    tokens: 268,
    text: '评审确认 Q3 聚焦解析质量与可追溯回答，其余需求顺延至 Q4…',
    before: '参会：产品、研发、设计。议题：Q3 路线图优先级。',
    after: '待办：各负责人在 9 月 5 日前补充排期。',
  },
  {
    n: 3,
    fileId: 'f_002',
    fileName: 'Q3 路线图规划.docx',
    fileType: 'DOCX',
    datasetId: 'ds_7f3a91c2',
    location: '第 3 节',
    section: '重点项目',
    score: 0.88,
    tokens: 356,
    text: '引用溯源由 刘洋 负责，已进入联调，计划 9 月 30 日全量上线…',
    before: '3. 重点项目：以下项目按优先级排序，均需在季度末前完成灰度。',
    after: '溯源能力上线后，回答中的每条结论都需要能跳转到原文位置。',
  },
  {
    n: 4,
    fileId: 'f_008',
    fileName: '版本迭代记录.md',
    fileType: 'MD',
    datasetId: 'ds_7f3a91c2',
    location: '第 4 节',
    section: 'v3.2',
    score: 0.79,
    tokens: 198,
    text: 'v3.2 完成知识库批量上传与解析进度展示，为多模态解析做准备…',
    before: 'v3.1：修复分块重叠导致的重复召回。',
    after: 'v3.3（规划中）：团队空间与成员权限。',
  },
  {
    n: 5,
    fileId: 'f_007',
    fileName: '需求池.xlsx',
    fileType: 'XLSX',
    datasetId: 'ds_7f3a91c2',
    location: '第 2 页',
    section: 'P0 需求',
    score: 0.74,
    tokens: 164,
    text: 'P0：扫描件解析、引用溯源、部门级知识库隔离…',
    before: '需求池按 P0 / P1 / P2 分级，每周评审一次。',
    after: 'P1：对话导出、知识库模板。',
  },
  {
    n: 6,
    fileId: 'f_002',
    fileName: 'Q3 路线图规划.docx',
    fileType: 'DOCX',
    datasetId: 'ds_7f3a91c2',
    location: '第 5 节',
    section: '团队空间',
    score: 0.81,
    tokens: 322,
    text: '团队空间：知识库按部门隔离，支持只读成员与管理员两级权限…',
    before: '5. 团队空间：面向多部门协作场景。',
    after: '权限模型与现有账号体系打通，10 月底完成。',
  },
  {
    n: 7,
    fileId: 'f_004',
    fileName: '竞品分析报告.pdf',
    fileType: 'PDF',
    datasetId: 'ds_7f3a91c2',
    location: '第 23 页',
    section: '引用展示',
    score: 0.68,
    tokens: 240,
    text: '三家竞品均提供引用溯源，但只有一家能定位到页码…',
    before: '6. 引用展示对比。',
    after: '建议我方溯源支持页码与段落双定位。',
  },
  {
    n: 8,
    fileId: 'f_001',
    fileName: '产品需求文档_v3.2.pdf',
    fileType: 'PDF',
    datasetId: 'ds_7f3a91c2',
    location: '第 18 页',
    section: '第 5 章 权限',
    score: 0.64,
    tokens: 286,
    text: '成员权限：只读成员可提问与查看引用，不可上传或删除文件…',
    before: '5.1 角色：管理员、编辑者、只读成员。',
    after: '5.2 审计：记录文件的上传、删除与权限变更。',
  },
];

const DESIGNED_Q = 'Q3 路线图里优先级最高的三项是什么？各自负责人和上线时间？';
const DESIGNED_BLOCKS: AnswerBlock[] = [
  { kind: 'p', text: '根据《Q3 路线图规划》与《产品需求文档 v3.2》，本季度优先级最高的三项如下：' },
  { kind: 'item', n: 1, title: '知识库多模态解析', text: '支持扫描件 OCR 与图片理解，负责人 王蕾，计划 10 月 15 日灰度上线', cite: [1] },
  { kind: 'item', n: 2, title: '对话引用溯源', text: '回答中逐句标注来源片段并支持跳转原文，负责人 刘洋，9 月 30 日上线', cite: [3] },
  { kind: 'item', n: 3, title: '团队空间与权限', text: '按部门隔离知识库并支持只读成员，负责人 陈默，10 月底完成', cite: [6] },
  { kind: 'p', text: '其中第 2 项已进入联调阶段，是本月最接近交付的一项。' },
];

const datasetName = (id: string) => db.state.datasets.find((d) => d.id === id)?.name ?? '知识库';
const withName = (c: Omit<RetrievedChunk, 'datasetName'>): RetrievedChunk => ({ ...c, datasetName: datasetName(c.datasetId) });

const doneSteps = (): ThinkingStep[] => [
  { key: 'understand', state: 'done', elapsed: 0.2 },
  { key: 'retrieve', state: 'done', elapsed: 0.6, detail: '召回 8 个片段，重排后保留 3 个' },
  { key: 'generate', state: 'done', elapsed: 1.6 },
];

function seedState(): ChatState {
  return {
    conversations: seedConversations.slice(0, 10).map((s, i) => {
      const chunks = s.datasetId === 'ds_7f3a91c2' ? CITE_DESIGNED.map(withName) : genericChunks(s.lastQuestion, [s.datasetId]);
      const blocks = i === 0 ? DESIGNED_BLOCKS : genericBlocks(s.lastQuestion, chunks);
      const question = i === 0 ? DESIGNED_Q : s.lastQuestion;
      return {
        id: s.id,
        title: s.title,
        datasetIds: [s.datasetId],
        model: s.model,
        pinned: false,
        updatedAt: s.updatedAt,
        messages: [
          { id: `${s.id}_u1`, role: 'user', text: question },
          {
            id: `${s.id}_a1`,
            role: 'assistant',
            status: 'done',
            model: s.model,
            steps: doneSteps(),
            startedAt: 0,
            thinkingElapsed: 0.8,
            totalElapsed: 2.4,
            chunks,
            blocks,
            shown: blocksLength(blocks),
          },
        ],
      };
    }),
  };
}

let state: ChatState = USE_MOCK ? seedState() : { conversations: [] };
let version = 0;
const listeners = new Set<() => void>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();

function emit() {
  version += 1;
  listeners.forEach((l) => l());
}

function patchConversation(id: string, fn: (c: Conversation) => Conversation) {
  state = { conversations: state.conversations.map((c) => (c.id === id ? fn(c) : c)) };
  emit();
}

function patchMessage(convId: string, msgId: string, fn: (m: AssistantMessage) => AssistantMessage) {
  patchConversation(convId, (c) => ({ ...c, messages: c.messages.map((m) => (m.id === msgId && m.role === 'assistant' ? fn(m) : m)) }));
}

export const chatStore = {
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  getVersion: () => version,
  get state() {
    return state;
  },
  /** 仅供测试 */
  reset() {
    timers.forEach((t) => clearTimeout(t));
    timers.clear();
    state = seedState();
    emit();
  },
};

const remote = createRemote({
  get: () => state.conversations,
  set: (conversations) => {
    state = { conversations };
    emit();
  },
  patchConversation,
  patchMessage,
});

/** 真实模式：加载会话列表（登录后调用） */
export const loadConversations = () => (USE_MOCK ? Promise.resolve() : remote.loadConversations());
/** 真实模式：打开会话时加载历史消息 */
export const ensureMessages = (id: string) => (USE_MOCK ? Promise.resolve() : remote.ensureMessages(id));

export function clearConversations() {
  state = { conversations: [] };
  emit();
}

export function useChat<T>(selector: (s: ChatState) => T): T {
  useSyncExternalStore(chatStore.subscribe, chatStore.getVersion);
  return selector(state);
}

export const getConversation = (id: string | undefined, s: ChatState = state) => s.conversations.find((c) => c.id === id);

/** 侧栏排序：置顶在前，其余保持最近更新顺序 */
export function sidebarConversations(s: ChatState = state) {
  return { pinned: s.conversations.filter((c) => c.pinned), recent: s.conversations.filter((c) => !c.pinned) };
}

export const roundsOf = (c: Conversation) => c.messages.filter((m) => m.role === 'user').length;

export function lastAssistant(c: Conversation | undefined): AssistantMessage | undefined {
  const list = c?.messages ?? [];
  for (let i = list.length - 1; i >= 0; i--) {
    const m = list[i];
    if (m.role === 'assistant') return m;
  }
  return undefined;
}

export const isBusy = (m: AssistantMessage | undefined) => !!m && (m.status === 'thinking' || m.status === 'streaming');

/* ---------------- 回答内容 ---------------- */

export function blocksLength(blocks: AnswerBlock[]) {
  return blocks.reduce((n, b) => n + (b.kind === 'item' ? b.title.length + b.text.length : b.text.length), 0);
}

/** 按已输出的字符数截取回答块（流式展示） */
export function revealBlocks(blocks: AnswerBlock[], shown: number) {
  const out: { block: AnswerBlock; title: string; text: string; complete: boolean }[] = [];
  let left = shown;
  for (const b of blocks) {
    if (left <= 0) break;
    if (b.kind === 'item') {
      const title = b.title.slice(0, left);
      left -= b.title.length;
      const text = left > 0 ? b.text.slice(0, left) : '';
      left -= b.text.length;
      out.push({ block: b, title, text, complete: left >= 0 });
    } else {
      out.push({ block: b, title: '', text: b.text.slice(0, left), complete: left >= b.text.length });
      left -= b.text.length;
    }
  }
  return out;
}

/** 通用召回：从所选知识库的已解析文件中挑选片段 */
function genericChunks(question: string, datasetIds: string[]): RetrievedChunk[] {
  const files = db.state.files.filter((f) => datasetIds.includes(f.datasetId) && f.status === 'done');
  if (!files.length) return [];
  const h = hashOf(question);
  const count = Math.min(8, Math.max(3, files.length * 2));
  return Array.from({ length: count }, (_, i) => {
    const f: KbFile = files[(h + i) % files.length];
    const text = SNIPPETS[(h + i) % SNIPPETS.length];
    return {
      n: i + 1,
      fileId: f.id,
      fileName: f.name,
      fileType: f.type,
      datasetId: f.datasetId,
      datasetName: datasetName(f.datasetId),
      location: `第 ${((h >> i) % 20) + 1} 页`,
      section: `第 ${(i % 5) + 1} 节`,
      score: Math.round((0.93 - i * 0.04) * 100) / 100,
      tokens: 180 + ((h + i * 53) % 260),
      text: `${text}…`,
      before: `《${f.name.replace(/\.[^.]+$/, '')}》相关章节概述。`,
      after: '以上内容以最新发布版本为准。',
    };
  });
}

function genericBlocks(question: string, chunks: RetrievedChunk[]): AnswerBlock[] {
  if (!chunks.length) return [{ kind: 'p', text: '所选知识库中暂未检索到与该问题相关的内容，可以换个问法，或选择其他知识库后再试。' }];
  const top = chunks.slice(0, 3);
  const docs = [...new Set(top.map((c) => `《${c.fileName.replace(/\.[^.]+$/, '')}》`))].slice(0, 2).join('与');
  const topic = question.replace(/[？?。！!]+$/, '').slice(0, 24);
  return [
    { kind: 'p', text: `根据${docs}，关于「${topic}」的要点如下：` },
    ...top.map<AnswerBlock>((c, i) => ({ kind: 'item', n: i + 1, title: c.section, text: c.text.replace(/…$/, ''), cite: [c.n] })),
    { kind: 'p', text: '如需进一步细节，可以继续追问，或点击片段编号查看原文。' },
  ];
}

/* ---------------- 发送与流式生成 ---------------- */

let seq = 0;
const nextId = (p: string) => `${p}_${Date.now().toString(36)}${(seq++).toString(36)}`;

const now = () => {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

export function defaultChatModel() {
  // 真实模式不回落到 Mock 模型名：未设置默认对话模型时为空，由发送时提示去模型配置
  return findModel(modelStore.state.defaults.chat)?.name ?? (USE_MOCK ? 'DeepSeek-V3' : '');
}

export function titleFrom(question: string) {
  const t = question.replace(/\s+/g, ' ').trim().replace(/[？?。！!]+$/, '');
  return t.length > 16 ? `${t.slice(0, 16)}…` : t;
}

/** F1 → F2（真实模式）：先在后端创建会话，再发送第一条消息；返回会话 ID */
export async function startConversationAsync(input: { question: string; datasetIds: string[]; model: string }): Promise<string> {
  if (USE_MOCK) return startConversation(input);
  const id = await remote.create(input);
  send(id, input.question);
  return id;
}

/** F1 → F2：创建对话并发送第一条消息 */
export function startConversation(input: { question: string; datasetIds: string[]; model: string }): string {
  const id = nextId('c');
  state = {
    conversations: [
      { id, title: titleFrom(input.question), datasetIds: input.datasetIds, model: input.model, pinned: false, updatedAt: '刚刚', messages: [] },
      ...state.conversations,
    ],
  };
  emit();
  send(id, input.question);
  return id;
}

/** 追问：生成中不允许再次发送（输入框可先输入） */
export function send(convId: string, question: string) {
  const conv = getConversation(convId);
  const text = question.trim().slice(0, QUESTION_MAX);
  if (!conv || !text || isBusy(lastAssistant(conv))) return;
  const answer: AssistantMessage = {
    id: nextId('a'),
    role: 'assistant',
    status: 'thinking',
    model: conv.model,
    steps: [
      { key: 'understand', state: 'active' },
      { key: 'retrieve', state: 'pending' },
      { key: 'generate', state: 'pending' },
    ],
    startedAt: Date.now(),
    chunks: [],
    blocks: [],
    shown: 0,
  };
  // 最近更新的对话移到列表顶部（置顶分组不受影响）
  state = {
    conversations: [
      { ...conv, updatedAt: '刚刚', messages: [...conv.messages, { id: nextId('u'), role: 'user', text }, answer] },
      ...state.conversations.filter((c) => c.id !== convId),
    ],
  };
  emit();
  if (USE_MOCK) run(convId, answer.id, text, false);
  else remote.run(convId, answer.id, text, conv.messages.length === 0);
}

function schedule(key: string, ms: number, fn: () => void) {
  timers.set(
    key,
    setTimeout(() => {
      timers.delete(key);
      fn();
    }, ms),
  );
}

const STREAM_TICK = 40;
const STREAM_CHARS = 5;

function run(convId: string, msgId: string, question: string, reuseRetrieval: boolean) {
  const conv = getConversation(convId)!;
  const retrieve = () => {
    const chunks =
      question === DESIGNED_Q || (conv.datasetIds.includes('ds_7f3a91c2') && /路线图|优先级|Q3/.test(question))
        ? CITE_DESIGNED.map(withName)
        : genericChunks(question, conv.datasetIds);
    const kept = Math.min(3, chunks.length);
    patchMessage(convId, msgId, (m) => ({
      ...m,
      chunks,
      steps: [m.steps[0], { key: 'retrieve', state: 'done', elapsed: 0.6, detail: `${conv.datasetIds.map(datasetName).join('、')} · 召回 ${chunks.length} 个片段，重排后保留 ${kept} 个` }, { key: 'generate', state: 'active' }],
    }));
    schedule(msgId, 300, generate);
  };

  const generate = () => {
    const m = getConversation(convId)?.messages.find((x) => x.id === msgId) as AssistantMessage | undefined;
    if (!m) return;
    // 「模拟失败」用于演示 F7：模型服务超时
    if (/模拟失败|超时/.test(question) && !reuseRetrieval) {
      patchMessage(convId, msgId, (x) => ({
        ...x,
        status: 'error',
        steps: x.steps.map((s) => (s.key === 'generate' ? { ...s, state: 'pending' } : s)),
        thinkingElapsed: (Date.now() - x.startedAt) / 1000,
        error: { message: `模型服务响应超时（${x.model} · 60s）。已检索到的 ${x.chunks.length} 个片段已保留，重新生成不会重复检索。`, requestId: `req_${msgId.slice(-8)}`, at: now() },
      }));
      return;
    }
    const blocks = question === DESIGNED_Q || m.chunks[0]?.n === 1 && m.chunks[0].fileId === 'f_001' ? DESIGNED_BLOCKS : genericBlocks(question, m.chunks);
    patchMessage(convId, msgId, (x) => ({ ...x, status: 'streaming', blocks, shown: 0, thinkingElapsed: (Date.now() - x.startedAt) / 1000 }));
    tick();
  };

  const tick = () => {
    const m = getConversation(convId)?.messages.find((x) => x.id === msgId) as AssistantMessage | undefined;
    if (!m || m.status !== 'streaming') return;
    const total = blocksLength(m.blocks);
    const shown = Math.min(total, m.shown + STREAM_CHARS);
    if (shown >= total) {
      patchMessage(convId, msgId, (x) => ({
        ...x,
        shown: total,
        status: 'done',
        totalElapsed: Math.round(((Date.now() - x.startedAt) / 1000) * 10) / 10,
        steps: x.steps.map((s) => (s.key === 'generate' ? { ...s, state: 'done', elapsed: Math.round(((Date.now() - x.startedAt) / 1000 - (x.thinkingElapsed ?? 0)) * 10) / 10 } : s)),
      }));
      return;
    }
    patchMessage(convId, msgId, (x) => ({ ...x, shown }));
    schedule(msgId, STREAM_TICK, tick);
  };

  if (reuseRetrieval) {
    schedule(msgId, 300, generate);
    return;
  }
  schedule(msgId, 400, () => {
    patchMessage(convId, msgId, (m) => ({
      ...m,
      steps: [{ key: 'understand', state: 'done', elapsed: 0.4, detail: '识别问题意图与关键词' }, { key: 'retrieve', state: 'active' }, m.steps[2]],
    }));
    schedule(msgId, 700, retrieve);
  });
}

/** 停止生成（Esc）：保留已输出的内容 */
export function stop(convId: string) {
  const m = lastAssistant(getConversation(convId));
  if (!m || !isBusy(m)) return;
  if (!USE_MOCK) return remote.stop(convId, m);
  clearTimeout(timers.get(m.id));
  timers.delete(m.id);
  patchMessage(convId, m.id, (x) => ({
    ...x,
    status: 'stopped',
    steps: x.steps.map((s) => (s.state === 'active' ? { ...s, state: 'pending' } : s)),
    thinkingElapsed: x.thinkingElapsed ?? (Date.now() - x.startedAt) / 1000,
  }));
}

/** 重新生成最后一条回答；失败后重试不重复检索。可同时切换模型（F7「换个模型重试」） */
export function regenerate(convId: string, model?: string) {
  const conv = getConversation(convId);
  const m = lastAssistant(conv);
  if (!conv || !m || isBusy(m)) return;
  const question = [...conv.messages].reverse().find((x) => x.role === 'user')?.text ?? '';
  const reuse = m.status === 'error' && m.chunks.length > 0;
  if (model) patchConversation(convId, (c) => ({ ...c, model }));
  patchMessage(convId, m.id, (x) => ({
    ...x,
    model: model ?? conv.model,
    status: 'thinking',
    error: undefined,
    feedback: undefined,
    blocks: [],
    shown: 0,
    startedAt: Date.now(),
    thinkingElapsed: undefined,
    totalElapsed: undefined,
    chunks: reuse ? x.chunks : [],
    steps: reuse
      ? [x.steps[0], x.steps[1], { key: 'generate', state: 'active' }]
      : [
          { key: 'understand', state: 'active' },
          { key: 'retrieve', state: 'pending' },
          { key: 'generate', state: 'pending' },
        ],
  }));
  // 真实模式：重新发起完整一轮（后端按新的 turn_id 落库）
  if (!USE_MOCK) return remote.run(convId, m.id, question, false);
  // 换模型重试时不再模拟失败
  run(convId, m.id, reuse && model ? question.replace(/模拟失败|超时/g, '') : question, reuse);
}

export function setFeedback(convId: string, msgId: string, feedback?: 'up') {
  patchMessage(convId, msgId, (m) => ({ ...m, feedback }));
}

/** 切换对话使用的知识库 / 模型（F3），对之后的提问生效 */
export function updateConversation(id: string, patch: Partial<Pick<Conversation, 'datasetIds' | 'model'>>) {
  patchConversation(id, (c) => ({ ...c, ...patch }));
}

export const TITLE_MAX = 40;

export async function renameConversation(id: string, title: string) {
  const t = title.trim().slice(0, TITLE_MAX);
  if (!t) throw new Error('标题不能为空');
  if (!USE_MOCK) await remote.rename(id, t);
  else await delay(80);
  patchConversation(id, (c) => ({ ...c, title: t }));
}

export function togglePin(id: string) {
  const next = !getConversation(id)?.pinned;
  if (!USE_MOCK) void remote.pin(id, next).catch(() => patchConversation(id, (c) => ({ ...c, pinned: !next })));
  patchConversation(id, (c) => ({ ...c, pinned: next }));
}

export async function deleteConversation(id: string) {
  const m = lastAssistant(getConversation(id));
  if (m) {
    clearTimeout(timers.get(m.id));
    timers.delete(m.id);
  }
  if (!USE_MOCK) await remote.remove(id);
  else await delay(120);
  state = { conversations: state.conversations.filter((c) => c.id !== id) };
  emit();
}

/** 最近使用的知识库（F1 快捷选择）：按对话出现顺序去重 */
export function recentDatasetIds(limit = 3) {
  const enabled = new Set(db.state.datasets.filter((d) => d.status === 'enabled').map((d) => d.id));
  return [...new Set(state.conversations.flatMap((c) => c.datasetIds))].filter((id) => enabled.has(id)).slice(0, limit);
}

/**
 * 首页 / 搜索使用的对话摘要。Mock 模式沿用设计稿种子数据；真实模式由当前会话列表派生
 * （未加载历史消息的会话只有标题与时间）。
 */
export function conversationSummaries(s: ChatState = state): ConversationSummary[] {
  if (USE_MOCK) return seedConversations;
  return s.conversations.map((c) => {
    const users = c.messages.filter((m): m is UserMessage => m.role === 'user');
    const last = lastAssistant(c);
    const chunks = last?.chunks ?? [];
    return {
      id: c.id,
      title: c.title,
      datasetId: c.datasetIds[0] ?? '',
      model: c.model,
      rounds: users.length,
      citedDocs: new Set(chunks.map((x) => x.fileId)).size,
      citedChunks: chunks.length,
      lastQuestion: users.at(-1)?.text ?? '',
      lastAnswerChars: last ? blocksLength(last.blocks) : 0,
      updatedAt: c.updatedAt,
    };
  });
}
