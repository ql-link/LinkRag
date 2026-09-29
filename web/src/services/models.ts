import { useSyncExternalStore } from 'react';

import { modelApi } from '@/api/endpoints';
import { USE_MOCK } from '@/api/http';
import { delay } from '@/mock/db';
import { catalogEntry, providerCatalog, seedModelState, toModels, toProvider } from '@/mock/models';
import type { Capability, ModelInfo, Provider } from '@/types';

import { CAP_TO_DTO, configIdOf, configIndex, toModelState } from './backend';

/**
 * 模型配置服务（D1–D4）。Mock 模式为内存模拟；真实模式对接 Python `/api/v1/llm/*`，
 * 写操作成功后重新拉取配置列表刷新本地状态。
 * 安全约定：API Key 只在「保存」时提交给后端，前端状态里只保存后端返回的脱敏值。
 */

interface ModelState {
  providers: Provider[];
  models: ModelInfo[];
  defaults: Record<Capability, string>;
}

let state: ModelState = USE_MOCK ? seedModelState() : { providers: [], models: [], defaults: {} as Record<Capability, string> };
let version = 0;
const listeners = new Set<() => void>();

function update(mutator: (draft: ModelState) => void) {
  const draft: ModelState = { providers: [...state.providers], models: [...state.models], defaults: { ...state.defaults } };
  mutator(draft);
  state = draft;
  version += 1;
  listeners.forEach((l) => l());
}

export const modelStore = {
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
    state = seedModelState();
    version += 1;
    listeners.forEach((l) => l());
  },
};

/** 真实模式：用后端数据整体替换状态 */
export function applyModelState(next: ModelState) {
  state = next;
  version += 1;
  listeners.forEach((l) => l());
}

async function reload() {
  const [configs, defaults] = await Promise.all([modelApi.configs(), modelApi.defaults()]);
  applyModelState(toModelState(configs, defaults));
}

export function useModels<T>(selector: (s: ModelState) => T): T {
  useSyncExternalStore(modelStore.subscribe, modelStore.getVersion);
  return selector(state);
}

export function providerOf(model: ModelInfo | undefined, s: ModelState = state) {
  return model ? s.providers.find((p) => p.id === model.providerId) : undefined;
}

export function findModel(id: string, s: ModelState = state) {
  return s.models.find((m) => m.id === id);
}

/** 可用 = 厂商已接入（内置或已配置密钥）且模型已启用 */
export function isAvailable(model: ModelInfo, s: ModelState = state) {
  const p = providerOf(model, s);
  return !!p && (p.builtin || !!p.maskedKey) && model.enabled;
}

/**
 * D4 下拉选项：个人（用户接入的厂商）/ 平台（内置）/ 不可用（目录中未配置密钥的厂商，置灰）
 */
export function modelOptions(cap: Capability, s: ModelState = state) {
  const ofCap = s.models.filter((m) => m.capabilities.includes(cap));
  const personal = ofCap.filter((m) => isAvailable(m, s) && !providerOf(m, s)?.builtin);
  const platform = ofCap.filter((m) => isAvailable(m, s) && providerOf(m, s)?.builtin);
  if (!USE_MOCK) return { personal, platform, unavailable: [], total: personal.length + platform.length };
  const configured = new Set(s.providers.map((p) => p.id));
  /** 不可用：未接入厂商的代表模型（每个厂商一个，最多 3 个），引导用户去添加厂商；已停用的模型不展示 */
  const shown = providerCatalog
    .filter((p) => !configured.has(p.id) && !p.needsBaseUrl)
    .map((p) => {
      const model = toModels(p).find((m) => m.capabilities.includes(cap));
      return model && { model, reason: '密钥未配置', providerName: p.name };
    })
    .filter((x): x is NonNullable<typeof x> => !!x)
    .slice(0, 3);
  return { personal, platform, unavailable: shown, total: personal.length + platform.length + shown.length };
}

export async function setDefault(cap: Capability, id: string) {
  const model = findModel(id);
  if (!model || !isAvailable(model)) throw new Error('该模型当前不可用');
  if (!USE_MOCK) {
    const configId = configIdOf(id, cap);
    if (!configId) throw new Error('该模型不支持此用途');
    await modelApi.setDefault(CAP_TO_DTO[cap], configId);
    return reload();
  }
  await delay(120);
  update((d) => {
    d.defaults[cap] = id;
  });
}

/** 该模型正作为哪些能力的默认模型（停用 / 移除前提示） */
export function defaultUsages(id: string, s: ModelState = state): Capability[] {
  return (Object.keys(s.defaults) as Capability[]).filter((c) => s.defaults[c] === id);
}

export function toggleModel(id: string, enabled: boolean) {
  if (!enabled && defaultUsages(id).length) throw new Error('该模型正在作为默认模型使用，请先切换默认模型');
  if (!USE_MOCK) {
    // 乐观更新；每个能力对应一条后端配置，逐条启停
    const ids = Object.values(configIndex.get(id) ?? {});
    update((d) => {
      d.models = d.models.map((m) => (m.id === id ? { ...m, enabled } : m));
    });
    void Promise.all(ids.map((cid) => modelApi.setActive(cid, enabled))).catch(() => reload());
    return;
  }
  update((d) => {
    d.models = d.models.map((m) => (m.id === id ? { ...m, enabled } : m));
  });
}

/* ---------------- 厂商接入（D2 / D3） ---------------- */

export function maskKey(key: string) {
  const k = key.trim();
  const prefix = k.startsWith('sk-') ? 'sk-' : k.slice(0, 3);
  return `${prefix}••••••••${k.slice(-4)}`;
}

export interface ConnectionResult {
  ok: boolean;
  latency?: number;
  modelCount?: number;
  message: string;
}

/** Mock 连接测试：以 sk- 开头且长度 ≥ 20 视为有效（真实环境由后端代为请求厂商接口） */
export async function testConnection(providerId: string, apiKey: string, baseUrl?: string): Promise<ConnectionResult> {
  if (!USE_MOCK) {
    // 后端在接入厂商时校验密钥；此处只做格式检查
    return apiKey.trim().length >= 8 ? { ok: true, message: '格式有效，保存时由服务端验证' } : { ok: false, message: '请填写有效的 API Key' };
  }
  await delay(700);
  const entry = catalogEntry(providerId);
  if (!entry) return { ok: false, message: '未知厂商' };
  if (entry.needsBaseUrl && !baseUrl?.trim() && !entry.defaultBaseUrl) return { ok: false, message: '请填写 Base URL' };
  if (baseUrl && !/^https?:\/\/[^\s]+$/.test(baseUrl.trim())) return { ok: false, message: 'Base URL 格式不正确' };
  const key = apiKey.trim();
  if (providerId !== 'ollama' && !(key.startsWith('sk-') && key.length >= 20)) return { ok: false, message: '密钥无效或已过期，请检查后重试' };
  return { ok: true, latency: 180 + ((key.length * 7) % 90), modelCount: entry.models.length, message: '连接成功' };
}

export async function saveProvider(input: { providerId: string; apiKey: string; baseUrl?: string; enabledModels: string[] }) {
  if (!USE_MOCK) {
    if (!input.apiKey.trim()) throw new Error('请填写 API Key');
    await modelApi.setupProvider(input.providerId, input.apiKey.trim());
    return reload();
  }
  const entry = catalogEntry(input.providerId);
  if (!entry) throw new Error('未知厂商');
  const existing = state.providers.find((p) => p.id === entry.id);
  /** 已接入的厂商留空密钥表示不修改，只更新启用的模型与 Base URL */
  const keepKey = !!existing?.maskedKey && !input.apiKey.trim();
  if (!keepKey) {
    const result = await testConnection(input.providerId, input.apiKey, input.baseUrl);
    if (!result.ok) throw new Error(result.message);
  } else {
    await delay(200);
  }
  const used = entry.models.filter((m) => !input.enabledModels.includes(m.name) && defaultUsages(`${entry.id}/${m.name}`).length);
  if (used.length) throw new Error(`${used.map((m) => m.name).join('、')} 正在作为默认模型使用，不能停用`);
  const disabled = entry.models.map((m) => m.name).filter((n) => !input.enabledModels.includes(n));
  const masked = keepKey ? existing!.maskedKey : input.providerId === 'ollama' && !input.apiKey.trim() ? '本地无需密钥' : maskKey(input.apiKey);
  const provider = { ...toProvider(entry, masked), baseUrl: input.baseUrl?.trim() || undefined };
  update((d) => {
    const exists = d.providers.some((p) => p.id === entry.id);
    const builtinIdx = d.providers.findIndex((p) => p.builtin);
    if (exists) {
      d.providers = d.providers.map((p) => (p.id === entry.id ? provider : p));
    } else {
      d.providers.splice(builtinIdx < 0 ? d.providers.length : builtinIdx, 0, provider);
    }
    const keep = d.models.filter((m) => m.providerId !== entry.id);
    d.models = [...keep, ...toModels(entry, disabled)];
  });
}

export function removeProvider(id: string) {
  const p = state.providers.find((x) => x.id === id);
  if (!p || p.builtin) return;
  const used = state.models.filter((m) => m.providerId === id && defaultUsages(m.id).length);
  if (used.length) throw new Error(`${used.map((m) => m.name).join('、')} 正在作为默认模型使用，请先切换`);
  if (!USE_MOCK) {
    const ids = state.models.filter((m) => m.providerId === id).flatMap((m) => Object.values(configIndex.get(m.id) ?? {}));
    update((d) => {
      d.providers = d.providers.filter((x) => x.id !== id);
      d.models = d.models.filter((m) => m.providerId !== id);
    });
    void Promise.all(ids.map((cid) => modelApi.remove(cid))).finally(() => reload());
    return;
  }
  update((d) => {
    d.providers = d.providers.filter((x) => x.id !== id);
    d.models = d.models.filter((m) => m.providerId !== id);
  });
}

export function catalogForAdd() {
  const configured = new Set(state.providers.map((p) => p.id));
  return providerCatalog.map((p) => ({ entry: p, configured: configured.has(p.id) }));
}

export function stats(s: ModelState = state) {
  return { providers: s.providers.length, models: s.models.length };
}
