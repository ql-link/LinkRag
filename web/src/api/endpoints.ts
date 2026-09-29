/**
 * 后端接口定义（Python 管理端 + RAG）。字段与 docs/api/http_contracts.md 保持一致：
 * 管理接口为 camelCase，RAG / 召回为 snake_case。
 */
import { fetchAll, request, type Page } from './http';

/* ---------------- 身份 ---------------- */

export interface LoginResult {
  accessToken: string;
  tokenType: 'Bearer';
  expiresIn: number;
  userId: number;
}

export interface ProfileDTO {
  id: number;
  username: string;
  nickname: string | null;
  email: string | null;
  phone: string | null;
  avatarUrl: string | null;
  role: 'ADMIN' | 'USER';
  status: number;
  bio: string | null;
  team: string | null;
  createdAt: string | null;
}

export const authApi = {
  login: (account: string, password: string) => request<LoginResult>('/api/v1/auth/login', { body: { account, password }, anonymous: true }),
  register: (username: string, email: string, password: string) =>
    request<LoginResult>('/api/v1/auth/register', { body: { username, email, password }, anonymous: true }),
  logout: () => request<null>('/api/v1/auth/logout', { method: 'POST' }),
  profile: () => request<ProfileDTO>('/api/v1/user/profile'),
  updateProfile: (patch: Partial<Pick<ProfileDTO, 'nickname' | 'email' | 'bio' | 'team'>>) =>
    request<null>('/api/v1/user/profile', { method: 'PATCH', body: patch }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<LoginResult>('/api/v1/user/password', { body: { currentPassword, newPassword } }),
};

/* ---------------- 模型配置 ---------------- */

export type CapabilityDTO = 'CHAT' | 'EMBEDDING' | 'SPARSE_EMBEDDING' | 'VISION' | 'RERANK' | 'ASR';

export interface ModelConfigDTO {
  configId: number;
  scope: 'SYSTEM' | 'USER';
  providerId: number;
  providerType: string;
  providerName: string;
  iconUrl: string | null;
  modelName: string;
  displayName: string | null;
  capability: CapabilityDTO;
  protocol: string;
  apiBaseUrl: string | null;
  apiKeyMasked: string | null;
  isActive: boolean;
  editable: boolean;
}

export interface ProviderCatalogDTO {
  providerType: string;
  providerName: string;
  iconUrl: string | null;
  models: { modelName: string; displayName: string | null; capabilities: { capability: CapabilityDTO; protocol: string; apiBaseUrl: string | null }[] }[];
}

export interface DefaultDTO {
  capability: CapabilityDTO;
  configId: number | null;
}

export const modelApi = {
  providers: () => request<ProviderCatalogDTO[]>('/api/v1/llm/providers'),
  configs: () => request<ModelConfigDTO[]>('/api/v1/llm/configs'),
  setupProvider: (providerType: string, apiKey: string) => request<ModelConfigDTO[]>('/api/v1/llm/configs/setup-provider', { body: { providerType, apiKey } }),
  setActive: (configId: number, isActive: boolean) => request<null>(`/api/v1/llm/configs/${configId}/active`, { method: 'PATCH', body: { isActive } }),
  remove: (configId: number) => request<null>(`/api/v1/llm/configs/${configId}`, { method: 'DELETE' }),
  defaults: () => request<DefaultDTO[]>('/api/v1/llm/defaults'),
  setDefault: (capability: CapabilityDTO, configId: number) => request<DefaultDTO>(`/api/v1/llm/defaults/${capability}`, { method: 'PUT', body: { configId } }),
};

/* ---------------- 数据集与文件 ---------------- */

export interface DatasetStatsDTO {
  fileCount: number;
  uploadingCount: number;
  failedCount: number;
  storageBytes: number;
  chunkCount: number;
}

export interface DatasetDTO {
  id: number;
  name: string;
  description: string | null;
  status: 'ACTIVE' | 'DISABLED';
  createdAt: string;
  updatedAt: string;
  stats?: DatasetStatsDTO;
}

export interface FileDTO {
  id: number;
  datasetId: number;
  originalFilename: string;
  fileSuffix: string | null;
  fileSize: number | null;
  uploadStatus: 'UPLOADING' | 'UPLOAD_SUCCESS' | 'UPLOAD_FAILED';
  isUploadSuccess: boolean;
  failureReason: string | null;
  createdAt: string;
  updatedAt: string;
}

export type ParseFrontendStatus = 'parse_success' | 'parse_failed' | 'parsing' | 'parse_waiting';

export interface ParseResultDTO {
  fileId: number;
  originalFilename: string;
  frontendStatus: ParseFrontendStatus | null;
  parseStatus: string | null;
  failureReason: string | null;
}

export interface ChunkDTO {
  chunkId: string;
  fileId: number;
  datasetId: number;
  index: number | null;
  chunkType: string;
  startLine: number | null;
  endLine: number | null;
  content: string;
  updatedAt: string;
}

export const datasetApi = {
  list: () => fetchAll<DatasetDTO>('/api/v1/datasets'),
  detail: (id: number) => request<DatasetDTO>(`/api/v1/datasets/${id}`),
  create: (input: { name: string; description?: string; denseEmbeddingConfigId: number; sparseEmbeddingConfigId: number }) =>
    request<DatasetDTO>('/api/v1/datasets', { body: input }),
  update: (id: number, patch: { name?: string; description?: string; status?: 'ACTIVE' | 'DISABLED' }) =>
    request<DatasetDTO>(`/api/v1/datasets/${id}`, { method: 'PATCH', body: patch }),
  remove: (id: number) => request<null>(`/api/v1/datasets/${id}`, { method: 'DELETE' }),
  /** 解析配置（仅取模型绑定字段；其余配置项页面暂未对接） */
  parseConfig: (id: number) =>
    request<{ dense_embedding_config_id: number | null; sparse_embedding_config_id: number | null }>(`/api/v1/datasets/${id}/parse-config`),
  files: (datasetId: number) => fetchAll<FileDTO>(`/api/v1/datasets/${datasetId}/files`),
  recentFiles: (pageSize = 5) => request<Page<FileDTO>>('/api/v1/files/recent', { query: { page: 1, pageSize } }),
  parseResults: (datasetId: number, fileIds: number[]) =>
    request<ParseResultDTO[]>(`/api/v1/datasets/${datasetId}/files/parse-results`, { query: { fileIds: fileIds.join(',') } }),
  upload: (datasetId: number, file: File, parseImmediately: boolean) => {
    const form = new FormData();
    form.append('file', file);
    form.append('parseImmediately', String(parseImmediately));
    return request<FileDTO>(`/api/v1/datasets/${datasetId}/files`, { body: form });
  },
  parse: (fileId: number) => request<{ fileId: number; frontendStatus: ParseFrontendStatus }>(`/api/v1/files/${fileId}/parse`, { method: 'POST' }),
  removeFile: (fileId: number) => request<null>(`/api/v1/files/${fileId}`, { method: 'DELETE' }),
  chunks: (fileId: number, page = 1, pageSize = 50) => request<Page<ChunkDTO>>('/api/v1/knowledge/chunks', { query: { fileId, page, pageSize } }),
};

/* ---------------- 对话 ---------------- */

export interface ConversationDTO {
  id: number;
  title: string;
  datasetId: number;
  lastConfigId: number | null;
  lastModelName: string | null;
  isPinned: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface MessageDTO {
  id: number;
  conversationId: number;
  turnId: string | null;
  query: string | null;
  answer: string;
  configId: number | null;
  modelName: string | null;
  /** 引用的 chunk_id 列表 */
  references: string[] | null;
  status: 'GENERATING' | 'COMPLETED' | 'FAILED' | 'STOPPED';
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
}

export interface ChunkDetailDTO {
  chunkId: string;
  documentId: number;
  fileName: string;
  content: string;
}

export const chatApi = {
  list: () => fetchAll<ConversationDTO>('/api/v1/chat/conversations'),
  create: (datasetId: number, lastConfigId?: number) => request<ConversationDTO>('/api/v1/chat/conversations', { body: { datasetId, lastConfigId } }),
  update: (id: number, patch: { title?: string; isPinned?: boolean }) => request<ConversationDTO>(`/api/v1/chat/conversations/${id}`, { method: 'PATCH', body: patch }),
  remove: (id: number) => request<null>(`/api/v1/chat/conversations/${id}`, { method: 'DELETE' }),
  messages: (id: number) => fetchAll<MessageDTO>(`/api/v1/chat/conversations/${id}/messages`, {}, 100),
  chunkDetails: (chunkIds: string[]) => request<ChunkDetailDTO[]>('/api/v1/knowledge/chunks/batch', { body: { chunkIds } }),
  cancel: (turnId: string) => request<{ stopped: boolean }>(`/api/v1/rag/stream/${encodeURIComponent(turnId)}/cancel`, { method: 'POST', bearer: true }),
};

/* ---------------- 用量 ---------------- */

export interface UsageSummaryDTO {
  totalCalls: number;
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
  averageLatencyMs: number | null;
  successCalls: number;
  failedCalls: number;
  successRate: number | null;
}
export interface UsageDailyDTO {
  date: string;
  calls: number;
  totalTokens: number;
}
export interface UsageByModelDTO {
  providerType: string;
  modelName: string;
  calls: number;
  totalTokens: number;
}
export interface UsageTrendDTO {
  currentTokens: number;
  previousTokens: number;
  currentCalls: number;
  previousCalls: number;
  tokenGrowthRate: number | null;
  callGrowthRate: number | null;
}
export interface UsageLogDTO {
  id: number;
  modelName: string;
  stage: string;
  operation: string;
  totalTokens: number;
  latencyMs: number | null;
  status: string;
  errorMessage: string | null;
  createdAt: string;
}

type Range = { startDate: string; endDate: string; stage?: string };

export const usageApi = {
  summary: (r: Range) => request<UsageSummaryDTO>('/api/v1/llm/usage/summary', { query: r }),
  daily: (r: Range) => request<UsageDailyDTO[]>('/api/v1/llm/usage/daily', { query: r }),
  byModel: (r: Range) => request<UsageByModelDTO[]>('/api/v1/llm/usage/by-model', { query: r }),
  trend: (r: Range) => request<UsageTrendDTO>('/api/v1/llm/usage/trend', { query: r }),
  logs: (r: Range, page: number, pageSize: number) => request<Page<UsageLogDTO>>('/api/v1/llm/usage/logs', { query: { ...r, page, pageSize } }),
};
