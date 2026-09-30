/** 模型管理（管理台）接口与类型：厂商、模型能力、同步任务 / 候选、平台模型配置 */
import { request, type Page } from '@/api/http';

export const CAPABILITIES = ['CHAT', 'EMBEDDING', 'SPARSE_EMBEDDING', 'VISION', 'RERANK', 'ASR'] as const;
export type Capability = (typeof CAPABILITIES)[number];
export const PROTOCOLS = ['openai', 'anthropic', 'google', 'jina', 'dashscope', 'bge_m3', 'doubao_vision'] as const;
export type Protocol = (typeof PROTOCOLS)[number];

export const CAPABILITY_LABEL: Record<Capability, string> = {
  CHAT: '对话',
  EMBEDDING: '向量',
  SPARSE_EMBEDDING: '稀疏向量',
  VISION: '视觉',
  RERANK: '重排',
  ASR: '语音识别',
};

export interface Provider {
  id: number;
  providerType: string;
  providerName: string;
  iconUrl: string | null;
  iconObjectKey: string | null;
  apiBaseUrl: string;
  defaultProtocol: Protocol;
  isActive: boolean;
  priority: number;
  createdAt: string;
  updatedAt: string;
}

export interface ProviderModel {
  id: number;
  providerId: number;
  modelName: string;
  displayName: string | null;
  capability: Capability;
  protocol: Protocol;
  apiBaseUrl: string;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export type SyncStatus = 'RUNNING' | 'SUCCESS' | 'FAILED';
export interface SyncJob {
  id: number;
  providerId: number;
  syncSource: string;
  status: SyncStatus;
  addedCount: number | null;
  updatedCount: number | null;
  staleCount: number | null;
  errorMessage: string | null;
  startedAt: string;
  finishedAt: string | null;
}

export type ReviewStatus = 'PENDING' | 'REJECTED' | 'PUBLISHED';
export interface SyncCandidate {
  id: number;
  capability: Capability;
  jobId: number;
  providerId: number;
  syncSource: string;
  externalModelId: string;
  modelName: string;
  displayName: string | null;
  inferredCapability: Capability;
  inferredProtocol: Protocol | null;
  inferredApiBaseUrl: string | null;
  contextWindow: number | null;
  maxOutputTokens: number | null;
  releaseDate: string | null;
  inputModalities: unknown;
  outputModalities: unknown;
  rawMetadata: unknown;
  reviewStatus: ReviewStatus;
  matchedProviderModelId: number | null;
  lastSeenAt: string;
  createdAt: string;
  updatedAt: string;
}

export interface LlmConfig {
  configId: number;
  scope: string;
  providerId: number;
  providerType: string;
  providerName: string | null;
  iconUrl: string | null;
  modelName: string;
  displayName: string;
  capability: Capability;
  protocol: Protocol;
  apiBaseUrl: string;
  apiKeyMasked: string;
  isActive: boolean;
  editable: boolean;
  snapshotVersion: number;
  createdAt: string;
  updatedAt: string;
}

type Q = Record<string, string | number | boolean | undefined | null>;
const A = '/api/v1/admin';

/** 这些接口分页参数为 `size`（非 pageSize），单独实现拉全量 */
export async function fetchAllSized<T>(path: string, query: Q = {}, size = 100, maxPages = 20): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; page <= maxPages; page += 1) {
    const res = await request<Page<T>>(path, { query: { ...query, page, size } });
    out.push(...(res.items ?? []));
    if (!res.totalPages || page >= res.totalPages) break;
  }
  return out;
}

// ---- 厂商 ----
export const listProviders = () => fetchAllSized<Provider>(`${A}/providers`);
export type ProviderInput = Pick<Provider, 'providerName' | 'apiBaseUrl' | 'defaultProtocol' | 'priority'> & { providerType?: string; iconUrl?: string | null; iconObjectKey?: string | null };
export const createProvider = (b: ProviderInput) => request<null>(`${A}/providers`, { method: 'POST', body: { ...b, isActive: false } });
export const updateProvider = (id: number, b: Partial<ProviderInput>) => request<null>(`${A}/providers/${id}`, { method: 'PATCH', body: b });
export const deleteProvider = (id: number) => request<null>(`${A}/providers/${id}`, { method: 'DELETE' });
export const setProviderActive = (id: number, isActive: boolean) => request<null>(`${A}/providers/${id}/active`, { method: 'PATCH', query: { isActive } });
export function uploadProviderIcon(file: File) {
  const fd = new FormData();
  fd.append('file', file);
  return request<{ iconUrl: string; iconObjectKey: string }>(`${A}/providers/icon`, { method: 'POST', body: fd });
}

// ---- 模型能力 ----
export const listProviderModels = (q: Q = {}) => fetchAllSized<ProviderModel>(`${A}/provider-models`, q);
export type ModelInput = Pick<ProviderModel, 'modelName' | 'capability' | 'protocol' | 'apiBaseUrl'> & { displayName?: string | null };
export const createProviderModel = (providerId: number, b: ModelInput) => request<ProviderModel>(`${A}/providers/${providerId}/models`, { method: 'POST', body: b });
export const updateProviderModel = (id: number, b: Partial<ModelInput>) => request<ProviderModel>(`${A}/provider-models/${id}`, { method: 'PATCH', body: b });
export const setProviderModelActive = (id: number, isActive: boolean) => request<null>(`${A}/provider-models/${id}/active`, { method: 'PATCH', query: { isActive } });
export const deleteProviderModel = (id: number) => request<null>(`${A}/provider-models/${id}`, { method: 'DELETE' });

// ---- 同步 ----
export const runSync = (providerId: number) => request<SyncJob>(`${A}/providers/${providerId}/model-sync`, { method: 'POST', body: { syncSource: 'MODELS_DEV' } });
export const listSyncJobs = (q: Q = {}, page = 1, size = 20) => request<Page<SyncJob>>(`${A}/model-sync-jobs`, { query: { ...q, page, size } });
export const listCandidates = (q: Q = {}) => fetchAllSized<SyncCandidate>(`${A}/model-sync-candidates`, q);
export type PublishInput = { modelName?: string; displayName?: string; capability?: Capability; protocol?: Protocol; apiBaseUrl?: string };
export const publishCandidate = (id: number, b: PublishInput) => request<ProviderModel>(`${A}/model-sync-candidates/${id}/publish`, { method: 'POST', body: b });
export const publishCandidates = (candidateIds: number[], b: { modelName?: string; displayName?: string } = {}) =>
  request<ProviderModel[]>(`${A}/model-sync-candidates/publish`, { method: 'POST', body: { candidateIds, ...b } });
export const reviewCandidate = (id: number, reviewStatus: 'PENDING' | 'REJECTED') => request<null>(`${A}/model-sync-candidates/${id}/review`, { method: 'PATCH', body: { reviewStatus } });

// ---- 平台模型配置 ----
const L = `${A}/llm`;
export const listConfigs = (q: Q = {}) => request<LlmConfig[]>(`${L}/configs`, { query: q });
export type CatalogMutation = { providerId: number; modelName: string; displayName?: string; capability: Capability; protocol: Protocol; apiBaseUrl: string };
export type ConfigInput = { sourceProviderModelId?: number; catalogMutation?: CatalogMutation; apiKey?: string };
export const createConfig = (b: ConfigInput) => request<{ config: LlmConfig }>(`${L}/configs`, { method: 'POST', body: b });
export const updateConfig = (id: number, b: ConfigInput) => request<{ config: LlmConfig }>(`${L}/configs/${id}`, { method: 'PUT', body: b });
export const setConfigActive = (id: number, isActive: boolean) => request<null>(`${L}/configs/${id}/active`, { method: 'PATCH', body: { isActive } });
export const emergencyDisableConfig = (id: number) => request<null>(`${L}/configs/${id}/emergency-disable`, { method: 'POST', body: { confirmed: true } });
export const deleteConfig = (id: number) => request<null>(`${L}/configs/${id}`, { method: 'DELETE' });

/** 业务码：配置被知识库使用中 */
export const CODE_CONFIG_IN_USE = 10026;
export const CODE_PROVIDER_NO_ACTIVE_MODEL = 10019;
export const reorderProviders = (providerIds: number[]) => request<null>(`${A}/providers/order`, { method: 'PUT', body: { providerIds } });
