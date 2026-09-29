import systemLogo from '@/assets/brand/logo-mark.png';
import type { Capability, ModelInfo, Provider } from '@/types';

/**
 * 模型配置 Mock（D1–D4）：可接入的厂商目录 + 每个厂商可用的模型。
 * 真实环境中目录与连接测试由后端提供，密钥只提交给后端，前端只保留脱敏值。
 */

export const capabilityLabel: Record<Capability, string> = {
  chat: '对话',
  dense: '稠密向量',
  sparse: '稀疏向量',
  rerank: '重排',
  vision: '视觉',
  asr: '语音识别',
};

export const CAPABILITIES: Capability[] = ['chat', 'dense', 'sparse', 'rerank', 'vision', 'asr'];

type CatalogModel = Omit<ModelInfo, 'id' | 'providerId' | 'enabled'>;

interface CatalogEntry extends Omit<Provider, 'maskedKey' | 'baseUrl'> {
  models: CatalogModel[];
  /** 需要填写 Base URL（OpenAI 兼容 / 本地部署） */
  needsBaseUrl?: boolean;
}

const m = (name: string, capabilities: Capability[], extra: Partial<CatalogModel> = {}): CatalogModel => ({ name, capabilities, ...extra });

/** D2 厂商目录，顺序与设计稿一致；linkrag 为平台内置 */
export const providerCatalog: CatalogEntry[] = [
  {
    id: 'deepseek',
    name: 'DeepSeek',
    letter: 'D',
    color: '#4d6bfe',
    summary: '对话 · 推理',
    defaultBaseUrl: 'https://api.deepseek.com/v1',
    keyUrl: 'https://platform.deepseek.com/api_keys',
    models: [
      m('DeepSeek-V3', ['chat'], { context: '64K', price: 0.002 }),
      m('DeepSeek-R1', ['chat'], { tag: '推理', context: '64K', price: 0.004 }),
    ],
  },
  {
    id: 'qwen',
    name: '通义千问',
    letter: 'Q',
    color: '#615ced',
    summary: '对话 · 视觉 · 语音',
    defaultBaseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    keyUrl: 'https://bailian.console.aliyun.com/?apiKey=1',
    models: [
      m('Qwen-Max', ['chat'], { tag: '视觉', context: '32K', price: 0.02, supportsImage: true }),
      m('Qwen-VL-Max', ['vision'], { context: '32K', price: 0.02, supportsImage: true }),
      m('Paraformer-v2', ['asr'], { price: 0.00008 }),
      m('qwen-turbo', ['chat'], { tag: '快速', context: '128K', price: 0.0003 }),
      m('qwen-long', ['chat'], { tag: '长上下文', context: '10M', price: 0.0005 }),
      m('text-embedding-v3', ['dense'], { price: 0.0005 }),
      m('gte-rerank', ['rerank'], { price: 0.0008 }),
    ],
  },
  {
    id: 'siliconflow',
    name: '硅基流动',
    letter: 'S',
    color: '#7a5bd0',
    summary: '向量 · 重排 · 对话',
    defaultBaseUrl: 'https://api.siliconflow.cn/v1',
    keyUrl: 'https://cloud.siliconflow.cn/account/ak',
    models: [
      m('bge-reranker-v2', ['rerank'], { price: 0 }),
      m('bge-large-zh-v1.5', ['dense'], { price: 0 }),
      m('Qwen2.5-72B-Instruct', ['chat'], { context: '32K', price: 0.0041 }),
      m('DeepSeek-V2.5', ['chat'], { context: '32K', price: 0.00133 }),
    ],
  },
  {
    id: 'zhipu',
    name: '智谱 AI',
    letter: 'Z',
    color: '#3859ff',
    summary: '对话 · 视觉',
    defaultBaseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    keyUrl: 'https://open.bigmodel.cn/usercenter/apikeys',
    models: [
      m('GLM-4-Plus', ['chat'], { tag: '长上下文', context: '128K', price: 0.05 }),
      m('GLM-4-Air', ['chat'], { tag: '快速', context: '128K', price: 0.0005 }),
      m('GLM-4V-Plus', ['vision'], { context: '8K', price: 0.01, supportsImage: true }),
      m('embedding-3', ['dense'], { price: 0.0005 }),
    ],
  },
  {
    id: 'moonshot',
    name: '月之暗面',
    letter: 'K',
    color: '#1d1d1b',
    summary: '对话 · 长上下文',
    defaultBaseUrl: 'https://api.moonshot.cn/v1',
    keyUrl: 'https://platform.moonshot.cn/console/api-keys',
    models: [m('Moonshot-v1-128k', ['chat'], { tag: '长上下文', context: '128K', price: 0.06 })],
  },
  {
    id: 'openai-compatible',
    name: 'OpenAI 兼容',
    letter: 'O',
    color: '#10a37f',
    summary: '自定义 Base URL',
    needsBaseUrl: true,
    models: [m('gpt-4o-mini', ['chat'], { context: '128K', supportsImage: true }), m('text-embedding-3-small', ['dense'])],
  },
  {
    id: 'volcengine',
    name: '火山引擎',
    letter: 'V',
    color: '#e0461f',
    summary: '对话 · 向量',
    defaultBaseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    keyUrl: 'https://console.volcengine.com/ark',
    models: [m('Doubao-pro-32k', ['chat'], { context: '32K', price: 0.0008 }), m('Doubao-embedding', ['dense'], { price: 0.0005 })],
  },
  {
    id: 'qianfan',
    name: '百度千帆',
    letter: 'B',
    color: '#2468f2',
    summary: '对话 · 向量',
    defaultBaseUrl: 'https://qianfan.baidubce.com/v2',
    keyUrl: 'https://console.bce.baidu.com/iam/#/iam/apikey/list',
    models: [m('ERNIE-4.0-Turbo', ['chat'], { context: '128K', price: 0.02 }), m('bge-large-zh', ['dense'], { price: 0.0005 })],
  },
  {
    id: 'ollama',
    name: 'Ollama',
    letter: 'L',
    color: '#55554f',
    summary: '本地部署',
    needsBaseUrl: true,
    defaultBaseUrl: 'http://localhost:11434/v1',
    models: [m('llama3.1:8b', ['chat'], { context: '128K', price: 0 }), m('nomic-embed-text', ['dense'], { price: 0 })],
  },
];

export const platformProvider: CatalogEntry = {
  id: 'linkrag',
  name: 'LinkRAG 默认',
  letter: 'L',
  color: '#1d1d1b',
  iconUrl: systemLogo,
  summary: '平台内置 · 无需密钥',
  builtin: true,
  models: [
    m('LinkRAG Chat', ['chat'], { tag: '免费额度', context: '32K', price: 0 }),
    m('LinkRAG Lite', ['chat'], { tag: '快速', context: '16K', price: 0 }),
    m('bge-m3', ['dense'], { price: 0 }),
    m('BM25', ['sparse'], { price: 0 }),
  ],
};

export function catalogEntry(id: string): CatalogEntry | undefined {
  return id === platformProvider.id ? platformProvider : providerCatalog.find((p) => p.id === id);
}

export const modelId = (providerId: string, name: string) => `${providerId}/${name}`;

function toProvider(entry: CatalogEntry, maskedKey?: string): Provider {
  const { models: _models, needsBaseUrl: _n, ...rest } = entry;
  return { ...rest, maskedKey };
}

function toModels(entry: CatalogEntry, disabled: string[] = []): ModelInfo[] {
  return entry.models.map((cm) => ({ ...cm, id: modelId(entry.id, cm.name), providerId: entry.id, enabled: !disabled.includes(cm.name) }));
}

/** 设计稿 D1 的初始状态：DeepSeek / 通义千问 / 硅基流动 已配置 + 平台内置 */
export function seedModelState() {
  const deepseek = catalogEntry('deepseek')!;
  const qwen = catalogEntry('qwen')!;
  const silicon = catalogEntry('siliconflow')!;
  return {
    providers: [toProvider(deepseek, 'sk-••••••••3f9a'), toProvider(qwen, 'sk-••••••••82cd'), toProvider(silicon, 'sk-••••••••11e0'), toProvider(platformProvider)],
    models: [
      ...toModels(deepseek),
      ...toModels(qwen, ['qwen-long', 'text-embedding-v3', 'gte-rerank']),
      ...toModels(silicon),
      ...toModels(platformProvider),
    ],
    defaults: {
      chat: modelId('deepseek', 'DeepSeek-V3'),
      dense: modelId('linkrag', 'bge-m3'),
      sparse: modelId('linkrag', 'BM25'),
      rerank: modelId('siliconflow', 'bge-reranker-v2'),
      vision: modelId('qwen', 'Qwen-VL-Max'),
      asr: modelId('qwen', 'Paraformer-v2'),
    } as Record<Capability, string>,
  };
}

export { toModels, toProvider };
export type { CatalogEntry };
