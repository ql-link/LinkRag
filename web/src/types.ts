export type DatasetStatus = 'enabled' | 'disabled';

export type FileType = 'PDF' | 'DOCX' | 'MD' | 'TXT' | 'XLSX' | 'ZIP';

export interface Dataset {
  id: string;
  name: string;
  description: string;
  status: DatasetStatus;
  /** 封面插画上的主类型标签 */
  coverType: FileType;
  denseModel: string;
  sparseModel: string;
  chunkCount: number;
  conversationCount: number;
  storage: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  /** 上传后立即解析 */
  autoParse: boolean;
}

export type FileStatus = 'uploading' | 'queued' | 'parsing' | 'done' | 'failed';

export interface KbFile {
  id: string;
  datasetId: string;
  name: string;
  type: FileType;
  size: string;
  status: FileStatus;
  /** 0-100，上传中 / 解析中有效 */
  progress: number;
  chunkCount: number;
  /** 行内补充说明：失败原因、排队信息、解析阶段等 */
  note?: string;
  updatedAt: string;
  /** 上传日期 MM-DD（真实模式来自后端 createdAt） */
  uploadedAt?: string;
}

export interface User {
  username: string;
  displayName: string;
  email: string;
  /** 个人简介，可选 */
  bio?: string;
  /** 所在团队 / 部门，可选 */
  team?: string;
  /** 注册日期 YYYY-MM-DD */
  createdAt?: string;
  /** 角色：ADMIN 可进入管理台 */
  role?: 'ADMIN' | 'USER';
}

export interface ConversationSummary {
  id: string;
  title: string;
  datasetId: string;
  model: string;
  rounds: number;
  /** 引用的文档数 / 片段数 */
  citedDocs: number;
  citedChunks: number;
  lastQuestion: string;
  /** 最近一次回答字数 */
  lastAnswerChars: number;
  updatedAt: string;
}

/** 模型能力（D1 默认模型的 6 项） */
export type Capability = 'chat' | 'dense' | 'sparse' | 'rerank' | 'vision' | 'asr';

export interface ModelInfo {
  id: string;
  name: string;
  providerId: string;
  capabilities: Capability[];
  enabled: boolean;
  /** 下拉中的补充标签：推理 / 长上下文 / 快速 等 */
  tag?: string;
  context?: string;
  /** 单价，元 / 千 Token */
  price?: number;
  supportsImage?: boolean;
}

export interface Provider {
  id: string;
  name: string;
  letter: string;
  color: string;
  /** 厂商 logo（后端 sys_provider.icon_url）；为空时展示字母方块 */
  iconUrl?: string;
  /** 厂商卡片上的能力说明（D2） */
  summary: string;
  /** 平台内置厂商无需密钥，不可移除 */
  builtin?: boolean;
  /** 已脱敏的密钥；未配置时为空 */
  maskedKey?: string;
  baseUrl?: string;
  defaultBaseUrl?: string;
  keyUrl?: string;
}
