/**
 * 后端 HTTP 基础层：统一鉴权头、响应包 `{code,message,data}` 解包、错误与 401 处理。
 *
 * - 管理类接口（/api/v1/**）从 `satoken` 请求头读取 access JWT；
 * - RAG 流 / 召回接口读取 `Authorization: Bearer`，两者为同一个 token（见 docs/api/http_contracts.md）。
 * - 开发时由 Vite 把 /api 代理到本地后端（vite.config.ts）；部署时同源访问。
 */

import { track } from './pending';

const TOKEN_KEY = 'linkrag.token';

export interface StoredToken {
  accessToken: string;
  /** 过期时间（毫秒时间戳） */
  expiresAt: number;
  userId: number;
}

/** 是否使用内存 Mock（离线演示 / 单元测试）。设置 VITE_USE_MOCK=false 连接真实后端。 */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';

export class ApiError extends Error {
  constructor(
    message: string,
    /** 业务码：管理接口为整数，RAG 接口为字符串 */
    public code: number | string,
    public status: number,
    public data?: unknown,
  ) {
    super(message);
  }
}

export function getToken(): StoredToken | null {
  try {
    const raw = localStorage.getItem(TOKEN_KEY);
    return raw ? (JSON.parse(raw) as StoredToken) : null;
  } catch {
    return null;
  }
}

export function setToken(t: { accessToken: string; expiresIn: number; userId: number } | null) {
  if (!t) return localStorage.removeItem(TOKEN_KEY);
  const stored: StoredToken = { accessToken: t.accessToken, expiresAt: Date.now() + t.expiresIn * 1000, userId: t.userId };
  localStorage.setItem(TOKEN_KEY, JSON.stringify(stored));
}

/** 登录失效（401）时的回调：由 AuthProvider 注册，负责清理登录态并跳转登录页 */
let onUnauthorized: (() => void) | undefined;
export function setUnauthorizedHandler(fn: (() => void) | undefined) {
  onUnauthorized = fn;
}

type Query = Record<string, string | number | boolean | undefined | null>;

export function withQuery(path: string, query?: Query) {
  if (!query) return path;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

interface RequestOptions {
  method?: string;
  query?: Query;
  /** JSON 请求体；FormData 原样发送 */
  body?: unknown;
  /** 使用 Bearer 头（RAG 接口）而非 satoken */
  bearer?: boolean;
  /** 不附带 token（登录 / 注册） */
  anonymous?: boolean;
  signal?: AbortSignal;
}

export function authHeaders(bearer = false): Record<string, string> {
  const t = getToken();
  if (!t) return {};
  return bearer ? { Authorization: `Bearer ${t.accessToken}` } : { satoken: t.accessToken };
}

// 续期：在过期前 10 分钟内的请求先换新 token（同一时刻只发一次）
const REFRESH_WINDOW_MS = 10 * 60 * 1000;
let refreshing: Promise<void> | null = null;

async function maybeRefresh() {
  const t = getToken();
  if (!t || t.expiresAt - Date.now() > REFRESH_WINDOW_MS || t.expiresAt <= Date.now()) return;
  refreshing ??= (async () => {
    try {
      const res = await fetch('/api/v1/auth/refresh', { method: 'POST', headers: { satoken: t.accessToken } });
      const body = await res.json().catch(() => null);
      if (res.ok && body?.code === 200 && body.data?.accessToken) setToken(body.data);
    } catch {
      // 续期失败不影响本次请求；token 真正过期时由 401 处理
    } finally {
      refreshing = null;
    }
  })();
  await refreshing;
}

async function parseError(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => null);
  const code = body?.code ?? res.status;
  const message = typeof body?.message === 'string' && body.message ? body.message : res.status >= 500 ? '服务暂时不可用，请稍后重试' : '请求失败';
  return new ApiError(message, code, res.status, body?.data);
}

/** 管理接口请求：返回解包后的 `data`；请求期间计入全局加载状态（顶部进度条） */
export function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return track(send<T>(path, opts));
}

async function send<T>(path: string, opts: RequestOptions): Promise<T> {
  if (!opts.anonymous) await maybeRefresh();
  const headers: Record<string, string> = opts.anonymous ? {} : authHeaders(opts.bearer);
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) body = opts.body;
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(withQuery(path, opts.query), { method: opts.method ?? (body ? 'POST' : 'GET'), headers, body, signal: opts.signal });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError('无法连接服务器，请检查网络或后端是否已启动', 'NETWORK', 0);
  }
  if (!res.ok) {
    const err = await parseError(res);
    if (res.status === 401 && !opts.anonymous) onUnauthorized?.();
    throw err;
  }
  const json = await res.json().catch(() => null);
  // 管理接口 code=200；RAG 取消接口 code="OK"
  if (json && typeof json === 'object' && 'code' in json) {
    if (json.code !== 200 && json.code !== 'OK') throw new ApiError(json.message || '请求失败', json.code, res.status, json.data);
    return json.data as T;
  }
  return json as T;
}

/** 分页响应 */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

/** 拉取分页接口的全部数据（管理端列表量级小；上限防止异常数据导致死循环） */
export async function fetchAll<T>(path: string, query: Query = {}, pageSize = 100, maxPages = 20): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; page <= maxPages; page += 1) {
    const res = await request<Page<T>>(path, { query: { ...query, page, pageSize } });
    out.push(...res.items);
    if (page >= res.totalPages) break;
  }
  return out;
}
