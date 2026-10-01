/**
 * 真实后端模式（VITE_USE_MOCK=false）下的数据装载与映射。
 *
 * 页面仍只依赖 services/* 暴露的同步选择器（db / modelStore / chatStore）；本模块负责
 * 从 Python 接口拉数据、映射为前端类型并写入这些 store。前端 ID 统一为后端数字 ID 的字符串形式，
 * 路由（/datasets/:id、/chat/:id）无需改动。
 */
import { chatApi, datasetApi, modelApi, type CapabilityDTO, type DatasetDTO, type FileDTO, type ModelConfigDTO, type ParseResultDTO } from '@/api/endpoints';
import { USE_MOCK } from '@/api/http';
import systemLogo from '@/assets/brand/logo-mark.png';
import { db, fileTypeFromName, formatSize } from '@/mock/db';
import { catalogEntry } from '@/mock/models';
import type { Capability, Dataset, KbFile, ModelInfo, Provider } from '@/types';

/* ---------------- 通用映射 ---------------- */

const CAP_FROM_DTO: Record<CapabilityDTO, Capability> = {
  CHAT: 'chat',
  EMBEDDING: 'dense',
  SPARSE_EMBEDDING: 'sparse',
  RERANK: 'rerank',
  VISION: 'vision',
  ASR: 'asr',
};
export const CAP_TO_DTO: Record<Capability, CapabilityDTO> = {
  chat: 'CHAT',
  dense: 'EMBEDDING',
  sparse: 'SPARSE_EMBEDDING',
  rerank: 'RERANK',
  vision: 'VISION',
  asr: 'ASR',
};

/** ISO 时间 → 列表展示用的相对标签（与 Mock 数据格式一致：今天 HH:mm / 昨天 / MM-DD） */
export function displayTime(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff === 0) return `今天 ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (diff === 1) return '昨天';
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function toDataset(dto: DatasetDTO, existing?: Dataset): Dataset {
  const s = dto.stats;
  return {
    id: String(dto.id),
    name: dto.name,
    description: dto.description ?? '',
    status: dto.status === 'DISABLED' ? 'disabled' : 'enabled',
    coverType: existing?.coverType ?? 'PDF',
    denseModel: existing?.denseModel ?? '',
    sparseModel: existing?.sparseModel ?? '',
    chunkCount: s?.chunkCount ?? existing?.chunkCount ?? 0,
    conversationCount: existing?.conversationCount ?? 0,
    storage: formatSize(s?.storageBytes ?? 0),
    createdBy: existing?.createdBy ?? '我',
    createdAt: dto.createdAt?.slice(0, 10) ?? '',
    updatedAt: displayTime(dto.updatedAt),
    autoParse: existing?.autoParse ?? true,
  };
}

/** 文件状态 = 上传状态 + 解析状态（parse-results.frontendStatus） */
export function toFile(dto: FileDTO, parse?: ParseResultDTO, existing?: KbFile): KbFile {
  let status: KbFile['status'] = 'queued';
  let note: string | undefined;
  if (dto.uploadStatus === 'UPLOADING') status = 'uploading';
  else if (dto.uploadStatus === 'UPLOAD_FAILED') {
    status = 'failed';
    note = dto.failureReason ?? '上传失败';
  } else {
    switch (parse?.frontendStatus) {
      case 'parse_success':
        status = 'done';
        break;
      case 'parse_failed':
        status = 'failed';
        note = parse.failureReason ?? '解析失败';
        break;
      case 'parsing':
        status = 'parsing';
        break;
      default:
        status = 'queued';
        note = '等待解析';
    }
  }
  const sameTask = existing?.status === status && existing?.parseTaskId === parse?.taskId;
  const stage = parse?.stageLabel ?? '文档解析';
  const sameStage = sameTask && existing?.progressStage === stage;
  const since = sameStage ? (existing?.progressSince ?? Date.now()) : Date.now();
  const base = Math.max(0, Math.min(99, parse?.progress ?? 0));
  const processing = parse?.stages?.filter((s) => s.status === 'PROCESSING').length ?? 1;
  // 无页数/字节遥测时，只在当前阶段范围内渐进估算；停止推进后永不到 100%。
  const room = parse?.stages ? Math.min(15, processing * 15) : 90;
  const estimating = status === 'parsing' && room > 0;
  const estimate = Math.floor(base + 1 + room * (1 - Math.exp(-(Date.now() - since) / 60000)));
  const progress = status === 'done' ? 100 : status === 'parsing'
    ? Math.min(99, Math.max(base, estimating ? estimate : base, sameTask ? (existing?.progress ?? 0) : 0))
    : status === 'uploading' ? (existing?.progress ?? 0) : 0;
  const estimated = status === 'uploading' || (status === 'parsing' && (estimating || progress > base));
  if (status === 'parsing') note = `${stage}${estimated ? ' · 进度为阶段估算' : ''}`;
  return {
    id: String(dto.id),
    datasetId: String(dto.datasetId),
    name: dto.originalFilename,
    type: fileTypeFromName(dto.originalFilename),
    size: formatSize(dto.fileSize ?? 0),
    status,
    progress,
    progressEstimated: estimated,
    parseTaskId: parse?.taskId,
    progressStage: stage,
    progressSince: since,
    chunkCount: existing?.chunkCount ?? 0,
    note,
    updatedAt: displayTime(parse?.updatedAt ?? dto.updatedAt),
    uploadedAt: dto.createdAt ? dto.createdAt.slice(5, 10) : undefined,
  };
}

/* ---------------- 模型 ---------------- */

/** 前端模型 ID（provider/model）→ 各能力对应的后端 configId */
export const configIndex = new Map<string, Partial<Record<Capability, number>>>();

/** 厂商 logo（GET /llm/providers 的 iconUrl，源自 sys_provider.icon_url），按 providerType 索引 */
const providerIcons = new Map<string, string>();
/** 前端厂商目录 ID 与后端 providerType 不一致的映射 */
const PROVIDER_ALIAS: Record<string, string> = { qwen: 'aliyun', zhipu: 'glm' };

export function providerIcon(id: string): string | undefined {
  if (id === 'linkrag') return SYSTEM_LOGO;
  return providerIcons.get(id) ?? providerIcons.get(PROVIDER_ALIAS[id] ?? '');
}

/** 模型名 → 模型所属厂商（平台内置厂商下的模型来自不同厂商，按名称识别） */
const MODEL_VENDOR: [RegExp, string][] = [
  [/deepseek/i, 'deepseek'],
  [/qwen|qwq/i, 'aliyun'],
  [/glm|zhipu/i, 'glm'],
  [/kimi|moonshot/i, 'moonshot'],
  [/doubao|seed/i, 'volcengine'],
  [/hunyuan/i, 'hunyuan'],
  [/minimax|abab/i, 'minimax'],
  [/claude/i, 'claude'],
  [/gemini|gemma/i, 'gemini'],
  [/grok/i, 'xai'],
  [/gpt|o\d-|text-embedding|openai/i, 'openai'],
  [/jina/i, 'jina'],
  [/mimo/i, 'mimo'],
];

/** 平台内置（SYSTEM）厂商统一使用 LinkRag 品牌 logo（随前端打包，不依赖对象存储） */
export const SYSTEM_LOGO = systemLogo;

/**
 * 模型 logo：系统模型统一为系统 logo；用户接入的模型优先按模型名识别出的厂商 logo
 * （如 OpenRouter 下的 DeepSeek 模型），识别不到时用所属厂商 logo。
 */
export function modelIcon(modelName: string, provider?: Pick<Provider, 'builtin' | 'iconUrl'>): string | undefined {
  if (provider?.builtin) return provider.iconUrl;
  const vendor = MODEL_VENDOR.find(([re]) => re.test(modelName))?.[1];
  return (vendor && providerIcons.get(vendor)) || provider?.iconUrl;
}

export async function loadProviderIcons() {
  const list = await modelApi.providers();
  providerIcons.clear();
  for (const p of list) if (p.iconUrl) providerIcons.set(p.providerType, p.iconUrl);
}

export function configIdOf(modelId: string, cap: Capability): number | undefined {
  return configIndex.get(modelId)?.[cap];
}

/** 由 configId 反查前端模型 ID */
export function modelIdOfConfig(configId: number | null | undefined): string | undefined {
  if (configId == null) return undefined;
  for (const [id, caps] of configIndex) if (Object.values(caps).includes(configId)) return id;
  return undefined;
}

export function toModelState(configs: ModelConfigDTO[], defaults: { capability: CapabilityDTO; configId: number | null }[]) {
  configIndex.clear();
  const providers = new Map<string, Provider>();
  const models = new Map<string, ModelInfo>();
  for (const c of configs) {
    const pid = c.scope === 'SYSTEM' ? 'linkrag' : c.providerType;
    if (!providers.has(pid)) {
      const cat = catalogEntry(pid);
      providers.set(pid, {
        id: pid,
        name: c.scope === 'SYSTEM' ? 'LinkRAG 默认' : c.providerName || cat?.name || pid,
        letter: (cat?.letter ?? c.providerName?.[0] ?? pid[0] ?? '?').toUpperCase(),
        color: cat?.color ?? '#55554f',
        iconUrl: c.scope === 'SYSTEM' ? SYSTEM_LOGO : (c.iconUrl ?? providerIcon(pid)),
        summary: cat?.summary ?? '',
        builtin: c.scope === 'SYSTEM' || undefined,
        maskedKey: c.scope === 'USER' ? (c.apiKeyMasked ?? '已配置') : undefined,
        baseUrl: c.apiBaseUrl ?? undefined,
        defaultBaseUrl: cat?.defaultBaseUrl,
        keyUrl: cat?.keyUrl,
      });
    }
    const cap = CAP_FROM_DTO[c.capability];
    if (!cap) continue;
    const name = c.displayName || c.modelName;
    const id = `${pid}/${c.modelName}`;
    const cur = models.get(id);
    models.set(id, {
      id,
      name,
      providerId: pid,
      capabilities: cur ? [...new Set([...cur.capabilities, cap])] : [cap],
      enabled: (cur?.enabled ?? true) && c.isActive,
    });
    configIndex.set(id, { ...configIndex.get(id), [cap]: c.configId });
  }
  const defaultMap = {} as Record<Capability, string>;
  for (const d of defaults) {
    const cap = CAP_FROM_DTO[d.capability];
    const id = modelIdOfConfig(d.configId);
    if (cap && id) defaultMap[cap] = id;
  }
  // 平台内置厂商排最后，与 Mock 展示顺序一致
  const list = [...providers.values()].sort((a, b) => Number(!!a.builtin) - Number(!!b.builtin));
  return { providers: list, models: [...models.values()], defaults: defaultMap };
}

/* ---------------- 装载 ---------------- */

let hydrated: Promise<void> | null = null;
const listeners = new Set<(ready: boolean) => void>();
let ready = USE_MOCK;

export function backendReady() {
  return ready;
}

export function onBackendReady(fn: (ready: boolean) => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function setReady(v: boolean) {
  ready = v;
  listeners.forEach((l) => l(v));
}

/** 按知识库拉取文件及解析状态 */
export async function loadFiles(datasetId: string, silent = false) {
  const dtos = await datasetApi.files(Number(datasetId), silent);
  const ids = dtos.filter((f) => f.uploadStatus === 'UPLOAD_SUCCESS').map((f) => f.id);
  const parse = new Map<number, ParseResultDTO>();
  // parse-results 按批查询，避免 URL 过长
  for (let i = 0; i < ids.length; i += 50) {
    for (const r of await datasetApi.parseResults(Number(datasetId), ids.slice(i, i + 50), silent)) parse.set(r.fileId, r);
  }
  db.update((d) => {
    const prev = new Map(d.files.map((f) => [f.id, f]));
    const others = d.files.filter((f) => f.datasetId !== datasetId);
    d.files = [...dtos.map((f) => toFile(f, parse.get(f.id), prev.get(String(f.id)))), ...d.files.filter((f) => f.datasetId === datasetId && f.id.startsWith('tmp_')), ...others];
    d.hiddenCounts[datasetId] = 0;
  });
}

export async function loadDatasets(silent = false) {
  const dtos = await datasetApi.list(silent);
  db.update((d) => {
    const prev = new Map(d.datasets.map((x) => [x.id, x]));
    d.datasets = dtos.map((x) => toDataset(x, prev.get(String(x.id))));
    // 列表页的文件数来自统计字段；未展开的文件通过 hiddenCounts 计入
    for (const x of dtos) {
      const loaded = d.files.filter((f) => f.datasetId === String(x.id)).length;
      d.hiddenCounts[String(x.id)] = Math.max(0, (x.stats?.fileCount ?? 0) - loaded);
    }
  });
}

/** 登录后拉取全部业务数据（模型 / 知识库 / 对话）；各模块失败互不影响 */
export function hydrateFromBackend(): Promise<void> {
  if (USE_MOCK) return Promise.resolve();
  hydrated ??= (async () => {
    const { applyModelState } = await import('./models');
    const { loadConversations } = await import('./chat');
    await Promise.allSettled([
      // 会话的模型名依赖 configIndex 反查：模型装载完成后再拉会话
      // 厂商 logo 先于模型状态装载，「添加厂商」列表与已接入厂商可同时显示 logo；失败时回退字母方块
      Promise.all([modelApi.configs(), modelApi.defaults(), loadProviderIcons().catch(() => undefined)])
        .then(([c, d]) => applyModelState(toModelState(c, d)))
        .finally(() => loadConversations()),
      // 首页「最近资料」需要文件列表：预取最近更新的几个知识库
      loadDatasets().then(() => Promise.allSettled(db.state.datasets.slice(0, 3).map((d) => loadFiles(d.id)))),
    ]);
  })()
    .catch(() => {
      hydrated = null;
    })
    // 各模块失败互不阻塞：无论结果如何都结束首屏加载，失败的模块按空数据展示
    .finally(() => setReady(true));
  return hydrated;
}

/** 退出登录：清空内存数据，避免下一位用户看到上一位的数据 */
export function resetBackendState() {
  if (USE_MOCK) return;
  hydrated = null;
  configIndex.clear();
  providerIcons.clear();
  setReady(false);
  db.update((d) => {
    d.datasets = [];
    d.files = [];
    d.hiddenCounts = {};
  });
  void import('./models').then((m) => m.applyModelState({ providers: [], models: [], defaults: {} as Record<Capability, string> }));
  void import('./chat').then((m) => m.clearConversations());
}

/** 把接口错误转为页面可展示的文案 */
export function errorText(e: unknown, fallback = '操作失败，请稍后重试') {
  return e instanceof Error && e.message ? e.message : fallback;
}

export { chatApi };
