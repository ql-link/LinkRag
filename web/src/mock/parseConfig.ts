/** 知识库解析配置（Mock）。字段与 Java 端 dataset parse-config 语义对齐，接入时按接口字段映射。 */
export interface ParseConfig {
  chunkMaxTokens: number;
  chunkOverlap: number;
  chunkMinTokens: number;
  forceSplitTokens: number;
  headingLevel: 1 | 2 | 3 | 4 | 5 | 6;
  resplitLong: boolean;
  structuredOverlap: boolean;

  imageEnhance: boolean;
  imageModel: string;
  tableEnhance: boolean;
  tableModel: string;
  headingRebuild: boolean;

  pdfParser: 'MinerU' | 'OpenDataLoader' | 'Naive';

  channels: { bm25: boolean; sparse: boolean; dense: boolean };
  weights: { bm25: number; sparse: number; dense: number };
  rerank: boolean;
  contextBudget: number;
}

export const DEFAULT_CONFIG: ParseConfig = {
  chunkMaxTokens: 512,
  chunkOverlap: 32,
  chunkMinTokens: 128,
  forceSplitTokens: 1024,
  headingLevel: 3,
  resplitLong: false,
  structuredOverlap: false,
  imageEnhance: true,
  imageModel: 'Qwen-VL-Max',
  tableEnhance: false,
  tableModel: 'DeepSeek-V3',
  headingRebuild: true,
  pdfParser: 'MinerU',
  channels: { bm25: true, sparse: true, dense: true },
  weights: { bm25: 0.3, sparse: 0.2, dense: 0.5 },
  rerank: true,
  contextBudget: 4096,
};

const saved = new Map<string, ParseConfig>();

export const clone = (c: ParseConfig): ParseConfig => JSON.parse(JSON.stringify(c));

export function loadConfig(datasetId: string): ParseConfig {
  return clone(saved.get(datasetId) ?? DEFAULT_CONFIG);
}

export async function saveConfig(datasetId: string, cfg: ParseConfig) {
  await new Promise((r) => setTimeout(r, 300));
  saved.set(datasetId, clone(cfg));
}

export const VISION_MODELS = ['Qwen-VL-Max', 'GPT-4o'];
export const CHAT_MODELS = ['DeepSeek-V3', 'Qwen-Max', 'GPT-4o'];

/** 比较两个配置的差异项（叶子字段），用于统计“未保存的修改” */
export function diffKeys(a: ParseConfig, b: ParseConfig): string[] {
  const out: string[] = [];
  const walk = (x: unknown, y: unknown, path: string) => {
    if (x && typeof x === 'object') {
      Object.keys(x as object).forEach((k) => walk((x as Record<string, unknown>)[k], (y as Record<string, unknown>)[k], path ? `${path}.${k}` : k));
    } else if (x !== y) out.push(path);
  };
  walk(a, b, '');
  return out;
}

export interface ConfigErrors {
  chunkMaxTokens?: string;
  chunkMinTokens?: string;
  forceSplitTokens?: string;
  channels?: string;
  weights?: string;
  contextBudget?: string;
}

export function validateConfig(c: ParseConfig): ConfigErrors {
  const e: ConfigErrors = {};
  if (c.chunkMaxTokens < 256 || c.chunkMaxTokens > 2048) e.chunkMaxTokens = '范围 256–2048';
  if (c.chunkMinTokens >= c.chunkMaxTokens) e.chunkMinTokens = '需小于目标片段上限';
  if (c.forceSplitTokens <= c.chunkMaxTokens) e.forceSplitTokens = '需大于目标片段上限';
  const on = (Object.keys(c.channels) as (keyof ParseConfig['channels'])[]).filter((k) => c.channels[k]);
  if (!on.length) e.channels = '至少启用一个召回通道';
  else if (on.reduce((n, k) => n + (Number(c.weights[k]) || 0), 0) <= 0) e.weights = '启用通道的总权重需大于 0';
  if (c.contextBudget < 1000 || c.contextBudget > 16000) e.contextBudget = '范围 1,000–16,000';
  return e;
}
