import { datasetApi } from '@/api/endpoints';
import { ApiError, USE_MOCK } from '@/api/http';
import { chunksFor, type Chunk } from '@/mock/chunks';
import { db, delay, fileTypeFromName, formatSize } from '@/mock/db';
import type { Dataset, KbFile } from '@/types';

import { configIdOf, hydrateFromBackend, loadDatasets, loadFiles, modelIdOfConfig, toDataset, toFile } from './backend';
import { modelOptions, modelStore } from './models';

/**
 * 知识库服务层。Mock 模式为内存模拟；真实模式对接 Python `/api/v1/datasets/**` 与 `/api/v1/files/**`：
 * 写操作先调接口再更新本地 store；上传 / 解析进度通过轮询 parse-results 刷新。
 * 页面组件只依赖这里导出的函数与类型。
 */

export interface CreateDatasetInput {
  name: string;
  description: string;
  denseModel: string;
  sparseModel: string;
}

const MOCK_DENSE = ['bge-m3', 'text-embedding-3-large', 'bge-large-zh-v1.5'];
const MOCK_SPARSE = ['BM25', 'SPLADE'];

/** 创建知识库时可选的向量模型：真实模式取用户可用的 EMBEDDING / SPARSE_EMBEDDING 配置，默认模型排首位 */
export function embeddingModels(kind: 'dense' | 'sparse'): string[] {
  if (USE_MOCK) return kind === 'dense' ? MOCK_DENSE : MOCK_SPARSE;
  const { personal, platform } = modelOptions(kind);
  const names = [...platform, ...personal].map((m) => m.name);
  const def = modelStore.state.models.find((m) => m.id === modelStore.state.defaults[kind])?.name;
  return def ? [def, ...names.filter((n) => n !== def)] : names;
}

export const NAME_MAX = 30;
export const DESC_MAX = 200;

export function fileCount(datasetId: string): number {
  const s = db.state;
  return s.files.filter((f) => f.datasetId === datasetId).length + (s.hiddenCounts[datasetId] ?? 0);
}

/** 详情页展示的文件统计（含未在列表中展开的已完成文件） */
export function fileStats(datasetId: string) {
  const s = db.state;
  const files = s.files.filter((f) => f.datasetId === datasetId);
  const hidden = s.hiddenCounts[datasetId] ?? 0;
  const count = (st: KbFile['status'][]) => files.filter((f) => st.includes(f.status)).length;
  return {
    total: files.length + hidden,
    done: count(['done']) + hidden,
    running: count(['uploading', 'queued', 'parsing']),
    parsing: count(['parsing', 'queued']),
    uploading: count(['uploading']),
    failed: count(['failed']),
  };
}

function embeddingConfigId(kind: 'dense' | 'sparse', name: string) {
  const model = modelStore.state.models.find((m) => m.name === name && m.capabilities.includes(kind));
  const id = model && configIdOf(model.id, kind);
  if (!id) throw new Error(kind === 'dense' ? '请先在模型配置中接入稠密向量模型' : '请先在模型配置中接入稀疏向量模型');
  return id;
}

function friendly(e: unknown): Error {
  if (e instanceof ApiError && e.status === 400 && /同名/.test(e.message)) return new Error('已存在同名知识库');
  if (e instanceof ApiError && e.code === 10028) return new Error('所选向量模型不可用，请检查模型配置');
  if (e instanceof ApiError && e.status === 503) return new Error(`${e.message}（请确认后端已开启对应写入开关）`);
  return e as Error;
}

export async function createDataset(input: CreateDatasetInput): Promise<Dataset> {
  if (!USE_MOCK) {
    try {
      const dto = await datasetApi.create({
        name: input.name.trim(),
        description: input.description.trim() || undefined,
        denseEmbeddingConfigId: embeddingConfigId('dense', input.denseModel),
        sparseEmbeddingConfigId: embeddingConfigId('sparse', input.sparseModel),
      });
      const ds = { ...toDataset(dto), denseModel: input.denseModel, sparseModel: input.sparseModel };
      db.update((d) => {
        d.datasets.unshift(ds);
        d.hiddenCounts[ds.id] = 0;
      });
      return ds;
    } catch (e) {
      throw friendly(e);
    }
  }
  await delay();
  const name = input.name.trim();
  if (db.state.datasets.some((d) => d.name === name)) {
    throw new Error('已存在同名知识库');
  }
  const ds: Dataset = {
    id: `ds_${Math.random().toString(16).slice(2, 10)}`,
    name,
    description: input.description.trim(),
    status: 'enabled',
    coverType: 'PDF',
    denseModel: input.denseModel,
    sparseModel: input.sparseModel,
    chunkCount: 0,
    conversationCount: 0,
    storage: '0 KB',
    createdBy: '陈默',
    createdAt: new Date().toISOString().slice(0, 10),
    updatedAt: '刚刚',
    autoParse: true,
  };
  db.update((d) => {
    d.datasets.unshift(ds);
  });
  return ds;
}

export async function updateDataset(id: string, patch: Partial<Pick<Dataset, 'name' | 'description' | 'status' | 'autoParse'>>) {
  if (!USE_MOCK) {
    const body: { name?: string; description?: string; status?: 'ACTIVE' | 'DISABLED' } = {};
    if (patch.name !== undefined) body.name = patch.name;
    if (patch.description !== undefined) body.description = patch.description;
    if (patch.status) body.status = patch.status === 'disabled' ? 'DISABLED' : 'ACTIVE';
    try {
      // autoParse 是前端偏好（上传时的 parseImmediately），不需要后端存储
      const dto = Object.keys(body).length ? await datasetApi.update(Number(id), body) : undefined;
      db.update((d) => {
        d.datasets = d.datasets.map((ds) => (ds.id === id ? { ...(dto ? toDataset(dto, ds) : ds), ...(patch.autoParse !== undefined && { autoParse: patch.autoParse }) } : ds));
      });
    } catch (e) {
      throw friendly(e);
    }
    return;
  }
  await delay(160);
  if (patch.name && db.state.datasets.some((d) => d.id !== id && d.name === patch.name)) {
    throw new Error('已存在同名知识库');
  }
  db.update((d) => {
    d.datasets = d.datasets.map((ds) => (ds.id === id ? { ...ds, ...patch, updatedAt: '刚刚' } : ds));
  });
}

export async function deleteDataset(id: string) {
  if (!USE_MOCK) {
    try {
      await datasetApi.remove(Number(id));
    } catch (e) {
      throw friendly(e);
    }
    db.update((d) => {
      d.datasets = d.datasets.filter((ds) => ds.id !== id);
      d.files = d.files.filter((f) => f.datasetId !== id);
      delete d.hiddenCounts[id];
    });
    return;
  }
  await delay();
  db.update((d) => {
    d.datasets = d.datasets.filter((ds) => ds.id !== id);
    d.files = d.files.filter((f) => f.datasetId !== id);
    delete d.hiddenCounts[id];
  });
}

/* ---------------- 文件 ---------------- */

const timers = new Map<string, ReturnType<typeof setInterval>>();

function patchFile(id: string, patch: Partial<KbFile>) {
  db.update((d) => {
    d.files = d.files.map((f) => (f.id === id ? { ...f, ...patch } : f));
  });
}

/** 模拟解析进度，完成后生成分块数 */
function runParse(fileId: string) {
  clearInterval(timers.get(fileId));
  patchFile(fileId, { status: 'parsing', progress: 0, note: undefined, updatedAt: '刚刚' });
  const t = setInterval(() => {
    const file = db.state.files.find((f) => f.id === fileId);
    if (!file || file.status !== 'parsing') return clearInterval(t);
    const next = Math.min(100, file.progress + 8 + Math.round(Math.random() * 10));
    if (next >= 100) {
      clearInterval(t);
      patchFile(fileId, { status: 'done', progress: 100, chunkCount: 8 + Math.round(Math.random() * 60), note: undefined });
    } else {
      patchFile(fileId, { progress: next });
    }
  }, 600);
  timers.set(fileId, t);
}


/* ---- 真实模式：上传 / 解析状态轮询 ---- */

const polls = new Map<string, ReturnType<typeof setInterval>>();

/** 有进行中的文件时每 3 秒刷新一次该知识库的文件与解析状态 */
function watchDataset(datasetId: string) {
  if (polls.has(datasetId)) return;
  const t = setInterval(async () => {
    try {
      await loadFiles(datasetId);
      await loadDatasets();
    } catch {
      return;
    }
    const busy = db.state.files.some((f) => f.datasetId === datasetId && ['uploading', 'parsing'].includes(f.status));
    if (!busy) {
      clearInterval(t);
      polls.delete(datasetId);
    }
  }, 3000);
  polls.set(datasetId, t);
}

/** 知识库列表 DTO 不含向量模型：详情页按解析配置里的绑定 configId 反查模型名 */
async function loadBoundModels(datasetId: string) {
  // 直达详情页时知识库列表 / 模型列表可能尚未装载：等登录后的首轮装载完成再反查
  await hydrateFromBackend();
  const ds = db.state.datasets.find((d) => d.id === datasetId);
  if (!ds || (ds.denseModel && ds.sparseModel)) return;
  const cfg = await datasetApi.parseConfig(Number(datasetId));
  const nameOf = (configId: number | null) => {
    const id = modelIdOfConfig(configId);
    return (id && modelStore.state.models.find((m) => m.id === id)?.name) || '';
  };
  const dense = nameOf(cfg.dense_embedding_config_id);
  const sparse = nameOf(cfg.sparse_embedding_config_id);
  db.update((d) => {
    d.datasets = d.datasets.map((x) => (x.id === datasetId ? { ...x, denseModel: x.denseModel || dense, sparseModel: x.sparseModel || sparse } : x));
  });
}

/** 进入知识库详情时调用：拉取文件列表与模型绑定，必要时开始轮询 */
export async function refreshFiles(datasetId: string) {
  if (USE_MOCK) return;
  // 文件列表与模型绑定并行拉取，全部返回后页面再一次性展示
  await Promise.all([loadBoundModels(datasetId).catch(() => undefined), loadFiles(datasetId)]);
  if (db.state.files.some((f) => f.datasetId === datasetId && ['uploading', 'parsing'].includes(f.status))) watchDataset(datasetId);
}

export function uploadFiles(datasetId: string, files: File[], autoParse: boolean): string[] {
  if (!USE_MOCK) {
    const placeholders: KbFile[] = files.map((file, i) => ({
      id: `tmp_${Date.now().toString(36)}_${i}`,
      datasetId,
      name: file.name,
      type: fileTypeFromName(file.name),
      size: formatSize(file.size),
      status: 'uploading',
      progress: 0,
      chunkCount: 0,
      updatedAt: '刚刚',
    }));
    db.update((d) => {
      d.files = [...placeholders, ...d.files];
    });
    placeholders.forEach((ph, i) => {
      datasetApi
        .upload(Number(datasetId), files[i], autoParse)
        .then((dto) => {
          db.update((d) => {
            d.files = d.files.map((f) => (f.id === ph.id ? toFile(dto) : f));
          });
        })
        .catch((e: unknown) => {
          db.update((d) => {
            d.files = d.files.map((f) => (f.id === ph.id ? { ...f, status: 'failed', note: e instanceof Error ? e.message : '上传失败' } : f));
          });
        })
        .finally(() => watchDataset(datasetId));
    });
    return placeholders.map((f) => f.id);
  }
  const created: KbFile[] = files.map((file, i) => ({
    id: `f_${Date.now().toString(36)}_${i}`,
    datasetId,
    name: file.name,
    type: fileTypeFromName(file.name),
    size: formatSize(file.size),
    status: 'uploading',
    progress: 0,
    chunkCount: 0,
    updatedAt: '刚刚',
  }));
  db.update((d) => {
    d.files = [...created, ...d.files];
    d.datasets = d.datasets.map((ds) => (ds.id === datasetId ? { ...ds, updatedAt: '刚刚' } : ds));
  });
  created.forEach((file) => {
    const t = setInterval(() => {
      const cur = db.state.files.find((f) => f.id === file.id);
      if (!cur || cur.status !== 'uploading') return clearInterval(t);
      const next = Math.min(100, cur.progress + 12 + Math.round(Math.random() * 18));
      if (next >= 100) {
        clearInterval(t);
        if (autoParse) runParse(file.id);
        else patchFile(file.id, { status: 'queued', progress: 0, note: '等待手动解析' });
      } else {
        patchFile(file.id, { progress: next });
      }
    }, 400);
    timers.set(file.id, t);
  });
  return created.map((f) => f.id);
}

export function cancelUploads(datasetId: string) {
  db.state.files
    .filter((f) => f.datasetId === datasetId && f.status === 'uploading')
    .forEach((f) => clearInterval(timers.get(f.id)));
  db.update((d) => {
    d.files = d.files.filter((f) => !(f.datasetId === datasetId && f.status === 'uploading'));
  });
}

export function reparseFile(fileId: string) {
  if (!USE_MOCK) {
    const file = db.state.files.find((f) => f.id === fileId);
    patchFile(fileId, { status: 'parsing', note: undefined });
    datasetApi
      .parse(Number(fileId))
      .catch((e: unknown) => patchFile(fileId, { status: 'failed', note: e instanceof Error ? e.message : '解析启动失败' }))
      .finally(() => file && watchDataset(file.datasetId));
    return;
  }
  runParse(fileId);
}

/** 解析所有待解析 / 失败的文件 */
export function parseAll(datasetId: string) {
  db.state.files
    .filter((f) => f.datasetId === datasetId && (f.status === 'queued' || f.status === 'failed'))
    .forEach((f) => (USE_MOCK ? runParse(f.id) : reparseFile(f.id)));
}

export function removeFile(fileId: string) {
  if (!USE_MOCK && !fileId.startsWith('tmp_')) void datasetApi.removeFile(Number(fileId)).then(() => loadDatasets());
  clearInterval(timers.get(fileId));
  db.update((d) => {
    d.files = d.files.filter((f) => f.id !== fileId);
  });
}

export function clearFailed(datasetId: string) {
  if (!USE_MOCK) {
    db.state.files.filter((f) => f.datasetId === datasetId && f.status === 'failed').forEach((f) => removeFile(f.id));
    return;
  }
  db.update((d) => {
    d.files = d.files.filter((f) => !(f.datasetId === datasetId && f.status === 'failed'));
  });
}

/* ---------------- 文件分块 ---------------- */

/** 读取已解析文件的分块：Mock 模式为本地生成，真实模式调用 GET /api/v1/knowledge/chunks */
export async function fetchChunks(file: KbFile): Promise<Chunk[]> {
  if (USE_MOCK) return chunksFor(file);
  const out: Chunk[] = [];
  for (let page = 1; page <= 40; page += 1) {
    const res = await datasetApi.chunks(Number(file.id), page, 100);
    for (const c of res.items) {
      out.push({
        id: c.chunkId,
        index: (c.index ?? out.length) + 1,
        kind: c.chunkType?.toLowerCase().includes('table') ? 'table' : c.chunkType?.toLowerCase().includes('image') ? 'image' : 'text',
        // 后端行号从 0 开始，展示按 1 起算
        section: c.startLine != null ? `第 ${c.startLine + 1}–${(c.endLine ?? c.startLine) + 1} 行` : '正文',
        page: 1,
        tokens: Math.max(1, Math.round(c.content.length / 1.6)),
        text: c.content,
        overlap: 0,
      });
    }
    if (page >= res.totalPages) break;
  }
  return out;
}
