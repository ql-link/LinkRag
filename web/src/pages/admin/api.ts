/** 管理台总览 / 用户接口（Python `/api/v1/admin/*`，字段见 docs/api/http_contracts.md） */
import { request, type Page } from '@/api/http';

export interface Metric {
  current: number;
  previous: number;
  growthRate: number | null;
}

export interface SyncJobBrief {
  id: number;
  providerId: number;
  providerName: string | null;
  status: 'RUNNING' | 'SUCCESS' | 'FAILED';
  addedCount: number | null;
  updatedCount: number | null;
  staleCount: number | null;
  errorMessage: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface OverviewDTO {
  users: { total: number; newThisMonth: number; active7d: Metric };
  models: { providers: number; activeProviderModels: number; platformConfigs: number };
  blog: { published: number; drafts: number; staleDrafts: number };
  feedback: { pending: number };
  /** 模型同步表未迁移时为 null */
  sync: { pendingCandidates: number; failedJobs7d: number; lastFailure: { providerName: string | null; errorMessage: string | null; startedAt: string | null } | null; recentJobs: SyncJobBrief[] } | null;
}

export interface DashboardDTO {
  rangeDays: 7 | 30 | 90;
  totalUsers: number;
  breakdown: { user: number; admin: number; enabled: number; disabled: number };
  newUsers: Metric;
  activeUsers: Metric;
  trend: { date: string; newUsers: number; activeUsers: number }[];
}

export interface AdminUserDTO {
  id: number;
  username: string;
  nickname: string | null;
  email: string | null;
  phone: string | null;
  avatarUrl: string | null;
  role: 'ADMIN' | 'USER';
  status: number;
  createdAt: string | null;
  lastLoginAt: string | null;
  datasetCount: number;
  tokens30d: number;
}

export interface UserDetailDTO extends Omit<AdminUserDTO, 'datasetCount' | 'tokens30d'> {
  bio: string | null;
  team: string | null;
  stats: {
    datasetCount: number;
    fileCount: number;
    fileBytes: number;
    conversationCount: number;
    conversations30d: number;
    promptTokens30d: number;
    completionTokens30d: number;
    tokens30d: number;
    modelConfigCount: number;
    modelProviders: string[];
  };
  datasets: { id: number; name: string; status: string; fileCount: number; fileBytes: number; updatedAt: string | null }[];
  recentLogins: LoginRecord[];
}

export interface LoginRecord {
  time: string | null;
  success: boolean;
  /** 成功：LOGIN / REGISTER */
  source: string | null;
  /** 失败：BAD_PASSWORD / DISABLED */
  reason: string | null;
  ip: string | null;
  userAgent: string | null;
}

export interface UserQuery {
  page: number;
  size: number;
  keyword?: string;
  role?: 'ADMIN' | 'USER';
  status?: 0 | 1;
  sort?: 'created' | 'lastLogin';
}

export interface LogItem {
  time: string;
  level: string | null;
  service: string | null;
  trace_id: string | null;
  message: string | null;
}

export const adminApi = {
  overview: () => request<OverviewDTO>('/api/v1/admin/overview'),
  dashboard: (days: 7 | 30 | 90) => request<DashboardDTO>('/api/v1/admin/users/dashboard', { query: { days } }),
  users: (q: UserQuery) => request<Page<AdminUserDTO>>('/api/v1/admin/users', { query: { ...q, withStats: true } }),
  user: (id: number) => request<UserDetailDTO>(`/api/v1/admin/users/${id}`),
  setStatus: (id: number, status: 0 | 1) => request<null>(`/api/v1/admin/users/${id}/status`, { method: 'PATCH', body: { status } }),
  /** 不传 newPassword 时由后端生成临时密码并返回一次 */
  resetPassword: (id: number, newPassword?: string) =>
    request<{ temporaryPassword: string | null }>(`/api/v1/admin/users/${id}/password/reset`, { body: newPassword ? { newPassword } : {} }),
  setRole: (id: number, role: 'ADMIN' | 'USER') => request<null>(`/api/v1/admin/users/${id}/role`, { method: 'PATCH', body: { role } }),
  /** 今日 ERROR 日志（Loki 代理；total 上限 1000） */
  errorLogs: (since: Date, pageSize = 5) =>
    request<Page<LogItem>>('/api/v1/admin/logs', { query: { level: 'ERROR', start_time: since.toISOString(), end_time: new Date().toISOString(), page: 1, page_size: pageSize } }),
};

/** 环比 → 「↑ 12.4%」；无上一周期返回 null */
export function growth(m: Metric): { text: string; up: boolean } | null {
  if (m.growthRate === null) return null;
  const pct = Math.abs(m.growthRate * 100).toFixed(1);
  return { text: `${m.growthRate >= 0 ? '↑' : '↓'} ${pct}%`, up: m.growthRate >= 0 };
}

/** 字节 → 1.8 GB / 612 MB */
export function bytes(n: number) {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${Math.round(n / 1024 ** 2)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

/** User-Agent → 「Chrome 129 · macOS」 */
export function device(ua: string | null | undefined): string {
  if (!ua) return '未知设备';
  const os = /iPhone|iPad/.test(ua)
    ? `iOS ${ua.match(/OS (\d+)/)?.[1] ?? ''}`.trim()
    : /Android/.test(ua)
      ? `Android ${ua.match(/Android (\d+)/)?.[1] ?? ''}`.trim()
      : /Mac OS X|Macintosh/.test(ua)
        ? 'macOS'
        : /Windows/.test(ua)
          ? 'Windows'
          : /Linux/.test(ua)
            ? 'Linux'
            : '';
  // Edge 的 UA 同时含 Chrome，需优先匹配
  const m = ua.match(/(Edg)\/(\d+)/) ?? ua.match(/(Firefox|Chrome|Version)\/(\d+)/);
  const name = !m ? (/curl|python|httpx|okhttp/i.test(ua) ? ua.split('/')[0] : '浏览器') : m[1] === 'Edg' ? `Edge ${m[2]}` : m[1] === 'Version' ? 'Safari' : `${m[1]} ${m[2]}`;
  return os ? `${name} · ${os}` : name;
}

/** IP 脱敏：116.228.**.** */
export const maskIp = (ip: string | null | undefined) => (!ip ? '—' : ip.includes('.') ? ip.replace(/^(\d+\.\d+)\..*$/, '$1.**.**') : ip.replace(/:[^:]+:[^:]+$/, ':****'));
