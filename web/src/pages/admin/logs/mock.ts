/** 日志追踪离线 Mock：生成最近 7 天的示例日志，筛选语义与后端一致（total 同样受 1000 行窗口限制） */
import type { Page } from '@/api/http';

import type { LogEntry, LogLabels } from './api';

interface Params {
  service?: string;
  level?: string;
  trace_id?: string;
  keyword?: string;
  start_time?: string;
  end_time?: string;
  page: number;
  page_size: number;
}

const TEMPLATES: Omit<LogEntry, 'time' | 'trace_id' | 'pid' | 'raw'>[] = [
  {
    level: 'ERROR',
    service: 'tolink-rag',
    host: 'rag-worker-2',
    logger_name: 'app.retrieval.milvus_client',
    message: '向量检索超时：milvus query exceeded 5000ms (collection=kb_1284)',
    exception:
      'TimeoutError: query timeout after 5000ms\n  File "retrieval/milvus_client.py", line 142, in search\n    res = await self._client.search(**kwargs)\n  File "pymilvus/client/grpc_handler.py", line 88, in search\n    raise MilvusException(code=1, message="deadline exceeded")',
  },
  { level: 'WARN', service: 'tolink-rag', host: 'rag-worker-2', logger_name: 'app.retrieval.retry', message: 'retry 1/2 for milvus search, backoff 400ms', exception: null },
  { level: 'ACCESS', service: 'tolink-service', host: 'svc-1', logger_name: 'ACCESS', message: 'POST /api/v1/chats/8812/messages 200 5210ms', exception: null },
  { level: 'INFO', service: 'tolink-rag', host: 'rag-worker-1', logger_name: 'app.pipeline.parse_task', message: 'parse task finished: doc=5521 chunks=184 cost=12.4s', exception: null },
  { level: 'AUDIT', service: 'tolink-service', host: 'svc-1', logger_name: 'AUDIT', message: 'admin#1 更新平台配置 deepseek-chat（apiKey 已更换）', exception: null },
  { level: 'WARN', service: 'tolink-service', host: 'svc-2', logger_name: 'quota.guard', message: '用户 32118 额度不足，已拒绝请求', exception: null },
  { level: 'ACCESS', service: 'tolink-service', host: 'svc-2', logger_name: 'ACCESS', message: 'GET /api/v1/datasets?page=1 200 38ms', exception: null },
  {
    level: 'ERROR',
    service: 'tolink-rag',
    host: 'rag-worker-1',
    logger_name: 'app.pipeline.ocr',
    message: '文档解析失败：PDF 第 14 页 OCR 返回空结果',
    exception: 'ValueError: empty OCR result for page 14\n  File "pipeline/parse_task/ocr.py", line 57, in run\n    raise ValueError(f"empty OCR result for page {page_no}")',
  },
  { level: 'DEBUG', service: 'tolink-rag', host: 'rag-worker-1', logger_name: 'app.mq.consumer', message: 'ack message offset=88213 topic=parse_task', exception: null },
];

let cache: { at: number; rows: LogEntry[] } | null = null;

/** 每 90 秒一条、覆盖 7 天；每 3 条共用一个 trace_id，便于演示链路追踪 */
function rows(now: number): LogEntry[] {
  if (cache && now - cache.at < 60_000) return cache.rows;
  const out: LogEntry[] = [];
  const count = (7 * 86_400_000) / 90_000;
  for (let i = 0; i < count; i += 1) {
    const t = TEMPLATES[i % TEMPLATES.length];
    const trace = ((Math.floor(i / 3) * 2654435761) >>> 0).toString(16).padStart(8, '0') + 'a1b2';
    const time = new Date(now - i * 90_000 - (i % 7) * 131).toISOString();
    out.push({ ...t, time, trace_id: trace.slice(0, 12), pid: String(31000 + (i % 900)), raw: JSON.stringify({ ts: time, lvl: t.level, trace_id: trace.slice(0, 12), msg: t.message }) });
  }
  cache = { at: now, rows: out };
  return out;
}

const delay = <T,>(v: T) => new Promise<T>((r) => setTimeout(() => r(v), 180));

export function mockQuery(p: Params): Promise<Page<LogEntry>> {
  const now = Date.now();
  const end = p.end_time ? new Date(p.end_time).getTime() : now;
  const start = p.start_time ? new Date(p.start_time).getTime() : end - 86_400_000;
  const kw = p.keyword?.toLowerCase();
  const hit = rows(now).filter((r) => {
    const t = new Date(r.time).getTime();
    if (t < start || t > end) return false;
    if (p.service && r.service !== p.service) return false;
    if (p.level && r.level !== p.level) return false;
    if (p.trace_id && r.trace_id !== p.trace_id) return false;
    if (kw && !`${r.message} ${r.exception ?? ''}`.toLowerCase().includes(kw)) return false;
    return true;
  });
  const fetched = hit.slice(0, Math.min(p.page * p.page_size, 1000));
  return delay({
    items: fetched.slice((p.page - 1) * p.page_size, p.page * p.page_size),
    total: fetched.length,
    page: p.page,
    pageSize: p.page_size,
    totalPages: Math.ceil(fetched.length / p.page_size),
  });
}

export const mockLabels = (): Promise<LogLabels> => delay({ services: ['tolink-rag', 'tolink-service'], levels: ['TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL', 'ACCESS', 'AUDIT'] });
