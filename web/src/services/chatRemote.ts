/**
 * 对话服务的真实后端实现（VITE_USE_MOCK=false）。
 *
 * - 会话：/api/v1/chat/conversations（管理接口，satoken）；
 * - 问答：POST /api/v1/rag/stream（SSE，Bearer），事件映射到 AssistantMessage 的既有字段，
 *   页面组件无需区分 Mock / 真实；
 * - 停止：POST /api/v1/rag/stream/{turn_id}/cancel，并中断本地读流。
 *
 * 引用：模型按「[片段N]」标注来源，N 对应本轮 hits 的顺序（从 1 开始）。
 */
import { chatApi, type ConversationDTO, type MessageDTO } from '@/api/endpoints';
import { streamAnswer, type StreamEvent, type StreamHit } from '@/api/stream';
import { db, fileTypeFromName } from '@/mock/db';

import { configIdOf, displayTime, modelIdOfConfig } from './backend';
import type { AnswerBlock, AssistantMessage, Conversation, Message, RetrievedChunk, ThinkingStep } from './chat';
import { findModel, modelStore } from './models';

export interface ChatStoreAccess {
  get: () => Conversation[];
  set: (list: Conversation[]) => void;
  patchConversation: (id: string, fn: (c: Conversation) => Conversation) => void;
  patchMessage: (convId: string, msgId: string, fn: (m: AssistantMessage) => AssistantMessage) => void;
}

const CITE_RE = /\[片段\s*(\d+)\]/g;

/** RAG 流错误码 → 用户可读文案（后端 message 为面向开发者的英文描述） */
const STREAM_ERRORS: Record<string, string> = {
  RECALL_ALL_SOURCES_FAILED: '检索服务暂时不可用，请稍后重试。',
  RECALL_TIMEOUT: '检索超时，请稍后重试或缩小知识库范围。',
  RECALL_GENERATION_FAILED: '模型生成回答失败，请稍后重试或切换对话模型。',
  RECALL_MODEL_CONFIG_MISSING: '所选对话模型不可用，请在「模型配置」中检查后重试。',
  RECALL_EMBEDDING_CONFIG_MISSING: '尚未设置默认稠密向量模型，请先在「模型配置」中设置。',
  DATASET_MODEL_BINDING_REQUIRED: '知识库未绑定向量模型，暂时无法检索。',
  RECALL_SCOPE_FORBIDDEN: '无权访问所选知识库。',
  RECALL_RATE_LIMITED: '提问过于频繁，请稍后再试。',
};

export const streamErrorText = (code: string | undefined, message?: string) => (code && STREAM_ERRORS[code]) || message || '回答生成失败';

/** 把答案文本切成段落块，并把「[片段N]」标注提取为 cite */
export function blocksFromAnswer(answer: string): AnswerBlock[] {
  return answer
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => {
      const cite = [...new Set([...p.matchAll(CITE_RE)].map((m) => Number(m[1])))];
      return { kind: 'p' as const, text: p.replace(CITE_RE, '').replace(/[ \t]+([，。；！？,.;!?])/g, '$1').trimEnd(), cite: cite.length ? cite : undefined };
    });
}

const datasetName = (id: string) => db.state.datasets.find((d) => d.id === id)?.name ?? '知识库';

export function toChunks(hits: StreamHit[]): RetrievedChunk[] {
  return hits.map((h, i) => {
    const name = h.file_name ?? `文档 #${h.doc_id}`;
    const text = h.content ?? '';
    return {
      n: i + 1,
      fileId: String(h.doc_id),
      fileName: name,
      fileType: fileTypeFromName(name),
      datasetId: String(h.dataset_id),
      datasetName: datasetName(String(h.dataset_id)),
      // 后端命中不含页码 / 章节：留空，避免与「片段 N」重复展示
      location: '',
      section: '',
      // 历史消息不含分数：NaN 表示未知，页面不展示
      score: h.rerank_score == null && h.fused_score == null ? NaN : Math.round((h.rerank_score ?? h.fused_score ?? 0) * 100) / 100,
      tokens: Math.max(1, Math.round(text.length / 1.6)),
      text: text.length > 120 ? `${text.slice(0, 120)}…` : text,
      before: '',
      after: '',
      full: text,
    } as RetrievedChunk;
  });
}

const modelNameOf = (configId: number | null, fallback: string | null) => {
  const id = modelIdOfConfig(configId);
  return (id && findModel(id)?.name) || fallback || '';
};

function toConversation(dto: ConversationDTO, existing?: Conversation): Conversation {
  return {
    id: String(dto.id),
    title: dto.title,
    datasetIds: existing?.datasetIds?.length ? existing.datasetIds : [String(dto.datasetId)],
    model: existing?.model || modelNameOf(dto.lastConfigId, dto.lastModelName),
    configId: dto.lastConfigId ?? existing?.configId,
    pinned: dto.isPinned,
    updatedAt: displayTime(dto.updatedAt),
    messages: existing?.messages ?? [],
    loaded: existing?.loaded,
  };
}

/** 历史轮次的思考步骤：成功轮次全部完成；失败 / 中断轮次无法还原进度，标为未开始 */
const historySteps = (done: boolean): ThinkingStep[] =>
  (['understand', 'retrieve', 'generate'] as const).map((key) => ({ key, state: done ? 'done' : 'pending' }));

/** 历史消息 → 页面消息；引用片段按 references 批量取正文 */
async function toMessages(dtos: MessageDTO[]): Promise<Message[]> {
  const allIds = [...new Set(dtos.flatMap((m) => m.references ?? []))];
  const details = new Map<string, { fileName: string; content: string; documentId: number }>();
  for (let i = 0; i < allIds.length; i += 100) {
    for (const d of await chatApi.chunkDetails(allIds.slice(i, i + 100)).catch(() => [])) details.set(d.chunkId, d);
  }
  return dtos.flatMap<Message>((m) => {
    const hits: StreamHit[] = (m.references ?? []).map((id) => {
      const d = details.get(id);
      return { chunk_id: id, doc_id: d?.documentId ?? 0, dataset_id: 0, file_name: d?.fileName ?? null, fused_score: null, rerank_score: null, content: d?.content ?? '' };
    });
    const blocks = blocksFromAnswer(m.answer ?? '');
    const status: AssistantMessage['status'] = m.status === 'FAILED' ? 'error' : m.status === 'STOPPED' ? 'stopped' : m.status === 'GENERATING' ? 'stopped' : 'done';
    const answer: AssistantMessage = {
      id: `a_${m.id}`,
      role: 'assistant',
      status,
      model: modelNameOf(m.configId, m.modelName),
      steps: historySteps(status === 'done' || blocks.length > 0),
      startedAt: 0,
      chunks: toChunks(hits),
      blocks,
      shown: blocks.reduce((n, b) => n + b.text.length, 0),
      turnId: m.turnId ?? undefined,
      error: m.status === 'FAILED' ? { message: streamErrorText(m.errorCode ?? undefined, m.errorMessage ?? undefined), requestId: m.turnId ?? '', at: displayTime(m.createdAt) } : undefined,
    };
    return [{ id: `u_${m.id}`, role: 'user', text: m.query ?? '' }, answer];
  });
}

export function createRemote(store: ChatStoreAccess) {
  const controllers = new Map<string, AbortController>();

  async function loadConversations() {
    const dtos = await chatApi.list();
    const prev = new Map(store.get().map((c) => [c.id, c]));
    store.set(dtos.map((d) => toConversation(d, prev.get(String(d.id)))));
  }

  async function ensureMessages(id: string) {
    const conv = store.get().find((c) => c.id === id);
    if (!conv || conv.loaded) return;
    const messages = await toMessages(await chatApi.messages(Number(id)));
    store.patchConversation(id, (c) => (c.loaded ? c : { ...c, messages, loaded: true }));
  }

  /** 模型展示名 → CHAT configId；历史会话的模型名可能是后端原始名（装载时模型列表未就绪），再按原始名与会话记录兜底 */
  function chatConfigId(model: string, fallback?: number) {
    const m = modelStore.state.models.find((x) => (x.name === model || x.id.endsWith(`/${model}`)) && x.capabilities.includes('chat'));
    return (m && configIdOf(m.id, 'chat')) || (fallback && modelIdOfConfig(fallback) ? fallback : undefined);
  }

  /** 发起一轮问答：流事件逐步写回同一条 AssistantMessage */
  function run(convId: string, msgId: string, question: string, isFirstTurn: boolean) {
    const conv = store.get().find((c) => c.id === convId);
    const configId = conv && chatConfigId(conv.model, conv.configId);
    const fail = (message: string) =>
      store.patchMessage(convId, msgId, (x) => ({
        ...x,
        status: 'error',
        steps: x.steps.map((s) => (s.state === 'active' ? { ...s, state: 'pending' } : s)),
        thinkingElapsed: x.thinkingElapsed ?? (Date.now() - x.startedAt) / 1000,
        error: { message, requestId: x.turnId ?? '', at: displayTime(new Date().toISOString()) },
      }));
    if (!conv || !configId) return fail('未找到可用的对话模型，请先在「模型配置」中接入并启用对话模型。');

    const turnId = crypto.randomUUID();
    const ctrl = new AbortController();
    controllers.set(msgId, ctrl);
    let text = '';
    const elapsed = (x: AssistantMessage) => Math.round(((Date.now() - x.startedAt) / 1000) * 10) / 10;
    store.patchMessage(convId, msgId, (x) => ({ ...x, turnId }));

    const onEvent = (e: StreamEvent) => {
      // 用户已停止：忽略后续进度 / 增量事件，只接受携带后端落库结果的终态事件
      const cur = store.get().find((c) => c.id === convId)?.messages.find((m) => m.id === msgId);
      if (cur?.role === 'assistant' && cur.status === 'stopped' && !['answer_stopped', 'answer_done', 'recall_done', 'error'].includes(e.event)) return;
      switch (e.event) {
        case 'recall_started':
          store.patchMessage(convId, msgId, (x) => ({
            ...x,
            steps: [{ key: 'understand', state: 'done', elapsed: elapsed(x) }, { key: 'retrieve', state: 'active' }, { key: 'generate', state: 'pending' }],
          }));
          break;
        case 'recall_hits': {
          const chunks = toChunks(e.data.hits);
          store.patchMessage(convId, msgId, (x) => ({
            ...x,
            chunks,
            steps: [
              x.steps[0],
              { key: 'retrieve', state: 'done', elapsed: Math.round((elapsed(x) - (x.steps[0].elapsed ?? 0)) * 10) / 10, detail: `${conv.datasetIds.map(datasetName).join('、')} · 召回 ${chunks.length} 个片段` },
              { key: 'generate', state: 'pending' },
            ],
          }));
          break;
        }
        case 'generation_started':
          store.patchMessage(convId, msgId, (x) => ({ ...x, steps: [x.steps[0], x.steps[1], { key: 'generate', state: 'active' }] }));
          break;
        case 'answer_delta': {
          text += e.data.text;
          const blocks = blocksFromAnswer(text);
          store.patchMessage(convId, msgId, (x) => ({
            ...x,
            status: 'streaming',
            thinkingElapsed: x.thinkingElapsed ?? elapsed(x),
            blocks,
            shown: blocks.reduce((n, b) => n + b.text.length, 0),
          }));
          break;
        }
        case 'conversation_title':
          store.patchConversation(convId, (c) => ({ ...c, title: e.data.title }));
          break;
        case 'answer_done':
        case 'answer_stopped':
        case 'recall_done': {
          const answer = e.event === 'recall_done' ? '所选知识库中暂未检索到与该问题相关的内容，可以换个问法，或选择其他知识库后再试。' : e.data.answer;
          const blocks = blocksFromAnswer(answer);
          const chunks = toChunks(e.data.hits);
          store.patchMessage(convId, msgId, (x) => ({
            ...x,
            status: e.event === 'answer_stopped' ? 'stopped' : 'done',
            chunks: chunks.length ? chunks : x.chunks,
            blocks,
            shown: blocks.reduce((n, b) => n + b.text.length, 0),
            thinkingElapsed: x.thinkingElapsed ?? elapsed(x),
            totalElapsed: e.event === 'answer_stopped' ? (x.totalElapsed ?? elapsed(x)) : elapsed(x),
            steps: x.steps.map((s) => (s.state === 'done' ? s : e.event === 'answer_stopped' ? { ...s, state: 'pending' } : { ...s, state: 'done' })),
          }));
          break;
        }
        case 'error':
          fail(streamErrorText(e.data.code, e.data.message));
          break;
      }
    };

    streamAnswer(
      { query: question, config_id: configId, conversation_id: Number(convId), turn_id: turnId, is_first_turn: isFirstTurn, dataset_ids: conv.datasetIds.map(Number) },
      onEvent,
      ctrl.signal,
    )
      .catch((err: unknown) => {
        if ((err as Error).name !== 'AbortError') fail((err as Error).message || '问答服务暂不可用');
      })
      .finally(() => {
        controllers.delete(msgId);
        // 连接异常结束但未收到终态：按停止处理，保留已输出内容
        store.patchMessage(convId, msgId, (x) =>
          x.status === 'thinking' || x.status === 'streaming' || (x.status === 'stopped' && x.steps.some((st) => st.state === 'active'))
            ? { ...x, status: 'stopped', totalElapsed: x.totalElapsed ?? elapsed(x), steps: x.steps.map((st) => (st.state === 'active' ? { ...st, state: 'pending' } : st)) }
            : x,
        );
      });
  }

  /** 停止生成：通知后端（跨 worker 生效）并断开本地读流 */
  function stop(convId: string, m: AssistantMessage) {
    if (m.turnId) void chatApi.cancel(m.turnId).catch(() => undefined);
    // 等待后端 answer_stopped 最多 2 秒，拿到后端落库的部分答案；超时再本地中断
    setTimeout(() => controllers.get(m.id)?.abort(), 2000);
    store.patchMessage(convId, m.id, (x) => ({
      ...x,
      status: 'stopped',
      totalElapsed: Math.round(((Date.now() - x.startedAt) / 1000) * 10) / 10,
      steps: x.steps.map((s) => (s.state === 'active' ? { ...s, state: 'pending' } : s)),
    }));
  }

  /** 新对话：后端会话按首个知识库创建（RAG 请求的 dataset_ids 可覆盖多个知识库） */
  async function create(input: { datasetIds: string[]; model: string }) {
    const dto = await chatApi.create(Number(input.datasetIds[0]), chatConfigId(input.model));
    const conv = { ...toConversation(dto), datasetIds: input.datasetIds, model: input.model, loaded: true };
    if (!conv.model) conv.model = modelNameOf(dto.lastConfigId, dto.lastModelName);
    store.set([conv, ...store.get()]);
    return conv.id;
  }

  return {
    loadConversations,
    ensureMessages,
    run,
    stop,
    create,
    rename: (id: string, title: string) => chatApi.update(Number(id), { title }),
    pin: (id: string, isPinned: boolean) => chatApi.update(Number(id), { isPinned }),
    remove: (id: string) => chatApi.remove(Number(id)),
  };
}

export { modelStore };
