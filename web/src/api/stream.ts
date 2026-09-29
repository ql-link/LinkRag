/**
 * RAG 问答流客户端：`POST /api/v1/rag/stream`，用 fetch + ReadableStream 读取 SSE
 * （EventSource 无法携带鉴权头）。事件与载荷见 docs/api/http_contracts.md §POST /api/v1/rag/stream。
 */
import { ApiError, authHeaders } from './http';

export interface StreamHit {
  chunk_id: string;
  doc_id: number;
  dataset_id: number;
  file_name: string | null;
  fused_score: number | null;
  rerank_score: number | null;
  content: string;
}

export type StreamEvent =
  | { event: 'stream_started'; data: { conversation_id: number; request_id: string } }
  | { event: 'recall_started'; data: Record<string, never> }
  | { event: 'recall_hits'; data: { hits: StreamHit[] } }
  | { event: 'generation_started'; data: Record<string, never> }
  | { event: 'answer_delta'; data: { text: string } }
  | { event: 'conversation_title'; data: { title: string } }
  | { event: 'answer_done'; data: { answer: string; hits: StreamHit[] } }
  | { event: 'answer_stopped'; data: { answer: string; hits: StreamHit[] } }
  | { event: 'recall_done'; data: { hits: StreamHit[] } }
  | { event: 'error'; data: { code: string; message: string } };

export interface StreamRequest {
  query: string;
  config_id: number;
  conversation_id: number;
  turn_id: string;
  is_first_turn: boolean;
  dataset_ids?: number[];
}

/** 解析 SSE 文本块：按空行分帧，取 event / data 行 */
export function parseSseFrames(buffer: string): { frames: { event: string; data: string }[]; rest: string } {
  const frames: { event: string; data: string }[] = [];
  const parts = buffer.split(/\r?\n\r?\n/);
  const rest = parts.pop() ?? '';
  for (const part of parts) {
    let event = 'message';
    const data: string[] = [];
    for (const line of part.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
    }
    if (data.length) frames.push({ event, data: data.join('\n') });
  }
  return { frames, rest };
}

/** 发起流式问答；逐个回调事件。未知事件忽略（增量兼容）。 */
export async function streamAnswer(req: StreamRequest, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch('/api/v1/rag/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(true) },
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.message || '问答服务暂不可用', body?.code ?? res.status, res.status);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseSseFrames(buffer + value);
    buffer = parsed.rest;
    for (const f of parsed.frames) {
      try {
        onEvent({ event: f.event, data: JSON.parse(f.data) } as StreamEvent);
      } catch {
        // 非 JSON 帧忽略
      }
    }
  }
}
