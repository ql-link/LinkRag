import type { ConversationSummary, Dataset, KbFile } from '@/types';

/** 前端 Mock 数据：内容与 Figma 设计稿保持一致，接入真实接口后删除 */
export const seedDatasets: Dataset[] = [
  {
    id: 'ds_7f3a91c2',
    name: '产品知识库',
    description: '产品需求、路线图与发布说明',
    status: 'enabled',
    coverType: 'PDF',
    denseModel: 'bge-m3',
    sparseModel: 'BM25',
    chunkCount: 35200,
    conversationCount: 18,
    storage: '1.28 GB',
    createdBy: '陈默',
    createdAt: '2026-08-12',
    updatedAt: '今天 14:20',
    autoParse: true,
  },
  {
    id: 'ds_2c81e04a',
    name: '技术文档库',
    description: 'API 说明、架构设计与运维手册',
    status: 'enabled',
    coverType: 'MD',
    denseModel: 'bge-m3',
    sparseModel: 'BM25',
    chunkCount: 21800,
    conversationCount: 42,
    storage: '640 MB',
    createdBy: '陈默',
    createdAt: '2026-07-03',
    updatedAt: '09-26',
    autoParse: true,
  },
  {
    id: 'ds_91bd3f70',
    name: '人事制度库',
    description: '员工手册、考勤与报销制度',
    status: 'enabled',
    coverType: 'DOCX',
    denseModel: 'bge-m3',
    sparseModel: 'BM25',
    chunkCount: 4100,
    conversationCount: 9,
    storage: '96 MB',
    createdBy: '陈默',
    createdAt: '2026-06-18',
    updatedAt: '09-25',
    autoParse: true,
  },
  {
    id: 'ds_5e0c2a19',
    name: '客服话术库',
    description: '售后流程、退款规则与常见问答',
    status: 'enabled',
    coverType: 'MD',
    denseModel: 'bge-m3',
    sparseModel: 'BM25',
    chunkCount: 12600,
    conversationCount: 27,
    storage: '210 MB',
    createdBy: '陈默',
    createdAt: '2026-06-02',
    updatedAt: '09-22',
    autoParse: true,
  },
  {
    id: 'ds_a47d6b88',
    name: '市场调研库',
    description: '竞品分析、用户访谈与行业报告',
    status: 'enabled',
    coverType: 'PDF',
    denseModel: 'bge-m3',
    sparseModel: 'BM25',
    chunkCount: 9800,
    conversationCount: 6,
    storage: '380 MB',
    createdBy: '陈默',
    createdAt: '2026-05-20',
    updatedAt: '09-18',
    autoParse: false,
  },
  {
    id: 'ds_c3f19e57',
    name: '数据指标库',
    description: '指标口径、看板说明与数据字典',
    status: 'enabled',
    coverType: 'XLSX',
    denseModel: 'bge-m3',
    sparseModel: 'BM25',
    chunkCount: 2300,
    conversationCount: 11,
    storage: '48 MB',
    createdBy: '陈默',
    createdAt: '2026-05-08',
    updatedAt: '09-10',
    autoParse: true,
  },
];

const f = (datasetId: string, id: string, name: string, type: KbFile['type'], size: string, rest: Partial<KbFile> = {}): KbFile => ({
  id,
  datasetId,
  name,
  type,
  size,
  status: 'done',
  progress: 100,
  chunkCount: 24,
  updatedAt: '今天',
  ...rest,
});

const P = 'ds_7f3a91c2';

export const seedFiles: KbFile[] = [
  f(P, 'f_001', '产品需求文档_v3.2.pdf', 'PDF', '2.4 MB', { chunkCount: 86 }),
  f(P, 'f_002', 'Q3 路线图规划.docx', 'DOCX', '860 KB', { chunkCount: 24 }),
  f(P, 'f_003', '发布说明_2026-09.md', 'MD', '42 KB', { status: 'parsing', progress: 62, chunkCount: 0 }),
  f(P, 'f_004', '竞品分析报告.pdf', 'PDF', '5.1 MB', { chunkCount: 132, updatedAt: '09-26' }),
  f(P, 'f_005', '用户访谈纪要.txt', 'TXT', '18 KB', { status: 'queued', progress: 0, chunkCount: 0, updatedAt: '09-25' }),
  f(P, 'f_006', '定价方案_扫描件.pdf', 'PDF', '12.8 MB', {
    status: 'failed',
    progress: 0,
    chunkCount: 0,
    note: '解析失败：OCR 识别超时，可重新解析',
    updatedAt: '09-24',
  }),
  f(P, 'f_007', '需求池.xlsx', 'XLSX', '230 KB', { chunkCount: 12, updatedAt: '09-23' }),
  f(P, 'f_008', '版本迭代记录.md', 'MD', '64 KB', { chunkCount: 31, updatedAt: '09-20' }),
  f(P, 'f_009', '用户调研报告.pdf', 'PDF', '8.6 MB', {
    status: 'parsing',
    progress: 45,
    chunkCount: 0,
    note: '正在识别表格与图片 · 第 12 / 27 页',
    updatedAt: '09-19',
  }),
  f(P, 'f_010', '产品原型说明.docx', 'DOCX', '1.4 MB', { status: 'parsing', progress: 18, chunkCount: 0, updatedAt: '09-19' }),
  f(P, 'f_011', '路线图评审纪要.md', 'MD', '42 KB', { chunkCount: 14, updatedAt: '09-20' }),
  f('ds_2c81e04a', 'f_t01', 'API 接口说明.md', 'MD', '128 KB', { chunkCount: 40, updatedAt: '09-26' }),
  f('ds_2c81e04a', 'f_t02', '技术路线图_v2.md', 'MD', '64 KB', { chunkCount: 22, updatedAt: '09-08' }),
  f('ds_91bd3f70', 'f_h01', '2026 员工手册.docx', 'DOCX', '3.2 MB', { status: 'parsing', progress: 42, chunkCount: 0, updatedAt: '09-25' }),
  f('ds_a47d6b88', 'f_m01', '2026 产品路线图.pdf', 'PDF', '5.1 MB', { chunkCount: 58, updatedAt: '09-12' }),
  f('ds_a47d6b88', 'f_m02', '竞品功能对照表.docx', 'DOCX', '620 KB', { chunkCount: 20, updatedAt: '09-18' }),
  f('ds_a47d6b88', 'f_m03', '竞品定价调研.md', 'MD', '36 KB', { chunkCount: 9, updatedAt: '09-10' }),
];

/** 首页「最近资料」按设计稿展示的文件（B2） */
export const seedRecentFileIds = ['f_001', 'f_t01', 'f_h01', 'f_002'];

/** 数据集的"其余文件"只以数量体现，避免 Mock 数据过大 */
export const seedHiddenFileCounts: Record<string, number> = {
  ds_7f3a91c2: 331,
  ds_2c81e04a: 216,
  ds_91bd3f70: 63,
  ds_5e0c2a19: 156,
  ds_a47d6b88: 94,
  ds_c3f19e57: 147,
};

const conv = (
  id: string,
  title: string,
  datasetId: string,
  model: string,
  rounds: number,
  lastQuestion: string,
  updatedAt: string,
  cited: [number, number] = [2, 5],
  lastAnswerChars = 860,
): ConversationSummary => ({ id, title, datasetId, model, rounds, lastQuestion, updatedAt, citedDocs: cited[0], citedChunks: cited[1], lastAnswerChars });

/** 前 8 条为侧栏「最近对话」 */
export const seedConversations: ConversationSummary[] = [
  conv('c_01', 'Q3 产品路线图要点', P, 'DeepSeek-V3', 6, '第 1 项的技术风险有哪些？', '12 分钟前', [3, 8], 1284),
  conv('c_02', '竞品分析报告对比', 'ds_a47d6b88', 'Qwen-Max', 8, '三家竞品在扫描件解析上的差异？', '09-24'),
  conv('c_03', 'API 鉴权流程说明', 'ds_2c81e04a', 'DeepSeek-V3', 4, 'Token 过期后如何刷新？', '09-23'),
  conv('c_04', '新员工入职手册总结', 'ds_91bd3f70', 'DeepSeek-V3', 3, '试用期考核包含哪些环节？', '09-22'),
  conv('c_05', '差旅报销标准查询', 'ds_91bd3f70', 'Qwen-Max', 2, '一线城市住宿标准是多少？', '09-21'),
  conv('c_06', '客服话术 · 退款流程', 'ds_5e0c2a19', 'DeepSeek-V3', 5, '超过 7 天的订单能否退款？', '09-19'),
  conv('c_07', '数据指标口径核对', 'ds_c3f19e57', 'DeepSeek-R1', 3, '活跃用户的统计口径是什么？', '09-17'),
  conv('c_08', '季度 OKR 草稿整理', P, 'DeepSeek-R1', 7, '把 KR 按负责人拆分一下', '09-15'),
  conv('c_09', '路线图与 OKR 对齐', P, 'DeepSeek-R1', 5, '哪些 OKR 没有对应路线图项目', '昨天'),
  conv('c_10', '竞品路线图对比', 'ds_a47d6b88', 'Qwen-Max', 4, '竞品下季度的重点方向是什么？', '09-22'),
];

/** 搜索页「最近搜索」的初始内容 */
export const seedRecentSearches = ['定价方案', '差旅报销标准', 'API 鉴权', '入职手册'];

export const seedConversationTotal = 128;
