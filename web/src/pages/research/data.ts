import { GITHUB_URL } from '@/pages/landing/shared';

/**
 * 设计稿「06 落地页」L6 研究与评测 / L7 评测报告详情 的展示数据。
 * 数值来自离线评测报告（最近更新 2026-09-29）；新增评测后在此同步。
 */

/**
 * 原始结果静态资源（web/public/research/raw/，由 scripts/pack_research_raw.py 生成）。
 * ZIP 含已找到原始产物的报告与 README；缺失项见 README「暂缺」。
 */
const RAW_BASE = '/research/raw';
export const ALL_RAW_RESULTS_URL: string | undefined = `${RAW_BASE}/linkrag-eval-2026-09-30.zip`;
const raw = (id: string) => `${RAW_BASE}/${id}.json`;
export const RELEASES_URL = `${GITHUB_URL}/releases`;
export const COMPARE_ISSUE_URL = `${GITHUB_URL}/issues/new`;

export const META: { label: string; value: string }[] = [
  { label: '最近更新', value: '2026-09-29' },
  { label: '评测轮次', value: 'R09–R13 · 5 轮' },
  { label: '对比项目', value: 'WeKnora（腾讯开源）' },
  { label: '数据集', value: 'BEIR SciFact · 旧四域基线' },
  { label: '指标', value: '源文档级 Recall · nDCG · MRR' },
];

/** 指标定义：用于指标名悬停提示（L9 · S7） */
export const METRIC_DEFS: Record<string, string> = {
  'Recall@1': '第 1 条结果是否就是标注为相关的文档。',
  'Recall@5': '前 5 条结果里找回了多少篇标注为相关的文档。',
  'Recall@10': '前 10 条结果里找回了多少篇标注为相关的文档。',
  'Recall@100': '前 100 条结果里找回了多少篇标注为相关的文档。',
  'nDCG@10': '前 10 条结果的排序质量：相关文档越靠前，得分越高。',
  'MRR@10': '第一篇相关文档排名的倒数，取前 10 条计算。',
  MRR: '第一篇相关文档排名的倒数的平均值。',
  'Hit Rate@5': '前 5 条结果中至少命中一篇相关文档的题目占比。',
};

export const OVERVIEW = [
  { value: '86.52%', unit: 'Recall@10', note: 'LinkRag 三路加权 · 产品 Top10 实测', source: 'R10 · 产品管线逐题复核', report: 'r10' },
  { value: '90.20%', unit: 'Recall@10', note: '三路前 30 chunk + 文本重排 · 离线实验', source: 'R13 · qwen3.7-text-rerank', report: 'r13' },
  { value: '88.42%', unit: 'Recall@10', note: '三路候选 + LambdaMART · 离线实验', source: 'R11 · train 809 题训练', report: 'r11' },
  { value: '211 ms', unit: '检索 P50', note: 'LinkRag 产品 Top10 · P95 468 ms', source: 'R10 · 顺序请求', report: 'r10' },
];

export const ADVANTAGES = [
  { value: '90.20%', sub: 'vs 89.53%', title: 'Recall@10 · 接同一文本重排后', desc: 'LinkRag 在 Recall@10、nDCG@10、MRR@10 上都更高', strong: true },
  { value: '+2.37', sub: '个百分点', title: 'Recall@5 · 原生检索', desc: '相关文档更早出现在前 5 条结果里' },
  { value: '+3.68', sub: 'vs +2.58', title: '重排带来的 Recall@10 提升', desc: '同一重排模型，LinkRag 的候选更能发挥作用' },
];

/** 开源对比：[指标, LinkRag, WeKnora, 差值]；差值为百分点，题数除外 */
export type CompareRow = [string, string, string, string];

export const COMPARE_STAGES: Record<'rerank' | 'native', { label: string; bars: CompareRow[]; table: CompareRow[] }> = {
  rerank: {
    label: '接同一重排后',
    bars: [
      ['Recall@10', '0.9020', '0.8953', '+0.67'],
      ['nDCG@10', '0.7889', '0.7869', '+0.20'],
      ['MRR@10', '0.7572', '0.7564', '+0.08'],
      ['前 30 候选覆盖', '0.9377', '0.9310', '+0.67'],
    ],
    table: [
      ['Recall@10', '0.9020', '0.8953', '+0.67'],
      ['nDCG@10', '0.7889', '0.7869', '+0.20'],
      ['MRR@10', '0.7572', '0.7564', '+0.08'],
      ['Recall@5', '0.8529', '0.8529', '持平'],
      ['Hit Rate@5', '0.8633', '0.8633', '持平'],
      ['Top10 命中题数', '273 / 300', '271 / 300', '+2'],
      ['前 30 候选覆盖上限', '0.9377', '0.9310', '+0.67'],
    ],
  },
  native: {
    label: '原生检索',
    bars: [
      ['Recall@5', '0.7991', '0.7754', '+2.37'],
      ['Hit Rate@5', '0.8133', '0.7967', '+1.66'],
      ['Recall@100', '0.9633', '0.9567', '+0.66'],
      ['MRR@10', '0.7037', '0.6990', '+0.47'],
    ],
    table: [
      ['Recall@5', '0.7991', '0.7754', '+2.37'],
      ['Hit Rate@5', '0.8133', '0.7967', '+1.66'],
      ['Recall@100', '0.9633', '0.9567', '+0.66'],
      ['MRR@10', '0.7037', '0.6990', '+0.47'],
    ],
  },
};

export const WHY = [
  { title: '候选质量更高', desc: '前 30 个候选覆盖了 93.77% 的相关文档，WeKnora 为 93.10%。重排能用上的正确答案更多。' },
  { title: '排序更靠前', desc: '原生检索阶段，LinkRag 的 Recall@5 高 2.37 个百分点，Hit Rate@5 高 1.66 个百分点。' },
  { title: '重排收益稳定', desc: '接入同一重排后 Recall@10 提升 3.68 个百分点，300 题配对检验的区间 [+1.34, +6.13] 全部为正。' },
];

export const PLANNED = ['RAGFlow', 'Dify', 'FastGPT'];

export const R10_CONFIGS = [
  { label: '仅稀疏', value: 0.7046 },
  { label: '仅 BM25', value: 0.7543 },
  { label: '三路 RRF', value: 0.8106 },
  { label: '仅稠密', value: 0.8509 },
  { label: '稠密 + BM25', value: 0.8609 },
  { label: '三路加权（产品默认）', value: 0.8652, strong: true },
];

export const ROUNDS = [
  { id: 'R09', report: 'r09', title: '旧四域基线', date: '2026-07-04—05', what: '稠密 / 稠密+BM25 / 三路加权路由对照', data: '四域 394 题 · 3,200 chunk', metric: 'Recall@1', from: '0.6393', to: '0.6507', path: '仅稠密 → 三路加权', delta: '+1.14', note: '三路把正例排得更靠前；数据集与后续轮次不同' },
  { id: 'R10', report: 'r10', title: 'SciFact 三路消融', date: '2026-09-29', what: '六种召回配置 + 产品管线逐题复核', data: 'SciFact · 5,183 篇 · 300 题', metric: 'Recall@10', from: '0.8509', to: '0.8652', path: '仅稠密 → 三路加权', delta: '+1.43', note: '产品 Top10 与离线结果逐题对账一致' },
  { id: 'R11', report: 'r11', title: 'LambdaMART 排序', date: '2026-09-29', what: 'train 809 题训练，在三路候选上离线重排', data: 'SciFact · 300 题', metric: 'Recall@10', from: '0.8652', to: '0.8842', path: '三路加权 → + LambdaMART', delta: '+1.90', note: '9 题改善、2 题变差；离线实验，尚未上线' },
  { id: 'R12', report: 'r12', title: '对比 WeKnora', date: '2026-09-29', what: '隔离部署 WeKnora，导入同一语料，原生检索对比', data: 'SciFact · 300 题', metric: 'Recall@5', from: '0.7754', to: '0.7991', path: 'WeKnora → LinkRag · 原生检索', delta: '+2.37', note: '同一语料、同名稠密模型、同口径评分' },
  { id: 'R13', report: 'r13', title: '文本重排', date: '2026-09-29', what: '双方各取前 30 chunk，接同一 qwen3.7-text-rerank', data: 'SciFact · 300 题', metric: 'Recall@10', from: '0.8652', to: '0.9020', path: '三路加权 → + 重排', delta: '+3.68', note: '双方接同一重排：LinkRag 0.9020，WeKnora 0.8953', latest: true },
];

/* ---------------- 历史报告 ---------------- */

export type ReportType = '四域基线' | '召回消融' | 'LambdaMART' | '文本重排' | '开源对比';
export const REPORT_TYPES: ReportType[] = ['四域基线', '召回消融', 'LambdaMART', '文本重排', '开源对比'];

export interface EvalVersion {
  id: string;
  desc: string;
}
export const VERSIONS: EvalVersion[] = [
  { id: 'v2026.09', desc: 'R10–R13 · SciFact' },
  { id: 'v2026.07', desc: 'R09 · 旧四域基线' },
  { id: 'v2026.06', desc: '早期消融' },
];

/** 报告内的一项指标：[指标, 本次, 对照（可选）, 差值（可选）] */
export type MetricRow = [string, string, string?, string?];

export interface Report {
  id: string;
  version: string;
  date: string;
  title: string;
  desc: string;
  type: ReportType;
  dataset: string;
  key: string;
  latest?: boolean;
  /** 摘要表的两列表头（本次 / 对照） */
  cols: [string, string];
  metrics: MetricRow[];
  config: [string, string][];
  /** 报告详情页 */
  lead: string;
  points: string[];
  env: [string, string][];
  chart?: { legend: string[]; groups: { label: string; values: number[] }[] };
  limits: string[];
  command?: string;
  /** 单份原始结果（web/public/research/raw/<id>.json）；仅对已公开且对账通过的报告赋值 */
  rawUrl?: string;
}

const SCIFACT_ENV: [string, string][] = [
  ['数据集', 'BEIR SciFact 官方包 · 5,183 篇文档 · 官方 test 300 题'],
  ['计分口径', '源文档级：同一文档的多个 chunk 只计一次'],
  ['LinkRag 版本', 'toLink-Rag 861f248 · Eval 0de8488'],
  ['统计方法', '300 题配对 bootstrap · 10,000 次 · seed 20260929'],
];

export const REPORTS: Report[] = [
  {
    id: 'r13',
    rawUrl: raw('r13'),
    version: 'v2026.09',
    date: '2026-09-29',
    title: 'R13 · 前 30 chunk 文本重排',
    desc: 'LinkRag 与 WeKnora 各取前 30，接同一 qwen3.7-text-rerank',
    type: '文本重排',
    dataset: 'SciFact · 300 题',
    key: 'R@10 0.9020 vs WeKnora 0.8953',
    latest: true,
    cols: ['LinkRag', 'WeKnora'],
    metrics: [
      ['Recall@10', '0.9020', '0.8953', '+0.67'],
      ['nDCG@10', '0.7889', '0.7869', '+0.20'],
      ['MRR@10', '0.7572', '0.7564', '+0.08'],
      ['前 30 候选覆盖', '0.9377', '0.9310', '+0.67'],
    ],
    config: [
      ['数据集', 'BEIR SciFact · 5,183 篇 · 300 题'],
      ['重排模型', 'qwen3.7-text-rerank'],
      ['重排输入', '双方各取前 30 chunk'],
      ['提升区间', 'Recall@10 [+1.34, +6.13]'],
    ],
    lead: '双方各取原生检索的前 30 个 chunk，接入同一个文本重排模型，比较重排后的检索质量。',
    points: [
      '接同一重排后，LinkRag 的 Recall@10 为 0.9020，WeKnora 为 0.8953。',
      '重排为 LinkRag 带来 +3.68 个百分点的 Recall@10 提升（WeKnora +2.58），300 题配对检验区间 [+1.34, +6.13] 全部为正。',
      '前 30 个候选覆盖了 93.77% 的相关文档，重排可用的正确答案更多。',
    ],
    env: [...SCIFACT_ENV, ['重排', 'qwen3.7-text-rerank · input_top_n 30'], ['WeKnora', '3e8b0bf · 隔离 Docker'], ['运行状态', '600 条重排响应 · sources_sha256 校验通过']],
    chart: {
      legend: ['WeKnora + 重排', 'LinkRag + 重排'],
      groups: [
        { label: 'Recall@10', values: [0.8953, 0.902] },
        { label: 'nDCG@10', values: [0.7869, 0.7889] },
        { label: 'MRR@10', values: [0.7564, 0.7572] },
        { label: '前 30 覆盖', values: [0.931, 0.9377] },
      ],
    },
    limits: ['重排为离线实验，尚未接入产品。', 'SciFact 为英文科学摘要检索，中文或其他文档类型的效果需另行评测。', '基于单次 300 题评测，差值较小的指标（MRR@10）在误差范围内。'],
    command: 'python scripts/benchmarks/rerank_scifact_top30.py --summarize',
  },
  {
    id: 'r12',
    rawUrl: raw('r12'),
    version: 'v2026.09',
    date: '2026-09-29',
    title: 'R12 · 对比 WeKnora 原生检索',
    desc: '隔离部署 WeKnora 3e8b0bf，导入同一 5,183 篇文档',
    type: '开源对比',
    dataset: 'SciFact · 300 题',
    key: 'R@5 0.7991 vs 0.7754',
    cols: ['LinkRag', 'WeKnora'],
    metrics: [
      ['Recall@5', '0.7991', '0.7754', '+2.37'],
      ['Hit Rate@5', '0.8133', '0.7967', '+1.66'],
      ['Recall@100', '0.9633', '0.9567', '+0.66'],
      ['MRR@10', '0.7037', '0.6990', '+0.47'],
    ],
    config: [
      ['数据集', 'BEIR SciFact · 5,183 篇 · 300 题'],
      ['稠密模型', 'text-embedding-v4 · 1024 维'],
      ['WeKnora', '3e8b0bf · 两路 RRF k=60'],
      ['原始产物', 'weknora/comparison.json'],
    ],
    lead: 'WeKnora 在隔离环境中导入同样的 5,183 篇文档，使用同名稠密模型，按源文档用同一套公式评分。',
    points: ['原生检索阶段，LinkRag 的 Recall@5 高 2.37 个百分点，相关文档更早出现在前 5 条结果里。', 'Hit Rate@5 高 1.66 个百分点，Recall@100 与 MRR@10 也略高。', '双方使用同一语料、同名稠密模型、同口径评分。'],
    env: [...SCIFACT_ENV, ['稠密模型', 'text-embedding-v4 · 1024 维'], ['WeKnora', '3e8b0bf · 两路 RRF k=60 · 隔离 Docker']],
    chart: {
      legend: ['WeKnora', 'LinkRag'],
      groups: [
        { label: 'Recall@5', values: [0.7754, 0.7991] },
        { label: 'Hit Rate@5', values: [0.7967, 0.8133] },
        { label: 'Recall@100', values: [0.9567, 0.9633] },
        { label: 'MRR@10', values: [0.699, 0.7037] },
      ],
    },
    limits: ['WeKnora 使用默认的两路 RRF 配置，未针对 SciFact 调参。', '只评检索，不涉及回答生成质量。'],
    command: 'python scripts/benchmarks/weknora_scifact.py evaluate',
  },
  {
    id: 'r11',
    rawUrl: raw('r11'),
    version: 'v2026.09',
    date: '2026-09-29',
    title: 'R11 · LambdaMART 排序',
    desc: 'train 809 题训练，三路候选上离线重排',
    type: 'LambdaMART',
    dataset: 'SciFact · 300 题',
    key: 'R@10 0.8652 → 0.8842',
    cols: ['+ LambdaMART', '三路加权'],
    metrics: [['Recall@10', '0.8842', '0.8652', '+1.90']],
    config: [
      ['数据集', 'BEIR SciFact · train 809 题训练 · test 300 题评测'],
      ['候选', '三路加权召回结果'],
      ['排序模型', 'LambdaMART'],
    ],
    lead: '用 SciFact train 集 809 题训练 LambdaMART，在三路加权的候选上做离线重排。',
    points: ['Recall@10 从 0.8652 提升到 0.8842（+1.90 个百分点）。', '300 题中 9 题改善、2 题变差。', '离线实验，尚未上线。'],
    env: [...SCIFACT_ENV, ['训练集', 'SciFact train · 809 题']],
    chart: { legend: ['三路加权', '+ LambdaMART'], groups: [{ label: 'Recall@10', values: [0.8652, 0.8842] }] },
    limits: ['训练与评测来自同一数据集的不同划分，跨领域泛化需另行验证。', '离线实验，尚未接入产品。'],
    command: 'scripts/benchmarks/run_scifact_lambdamart.sh fit-evaluate',
  },
  {
    id: 'r10',
    rawUrl: raw('r10'),
    version: 'v2026.09',
    date: '2026-09-29',
    title: 'R10 · SciFact 三路消融',
    desc: '六种召回配置 + 产品管线逐题复核',
    type: '召回消融',
    dataset: 'SciFact · 5,183 篇 · 300 题',
    key: 'R@10 0.8652（产品 Top10）',
    cols: ['Recall@10', ''],
    metrics: R10_CONFIGS.map((c) => [c.label, c.value.toFixed(4)] as MetricRow),
    config: [
      ['数据集', 'BEIR SciFact · 5,183 篇 · 300 题'],
      ['三路权重', '0.70 / 0.15 / 0.15'],
      ['RRF', 'k = 60'],
      ['延迟', '检索 P50 211 ms · P95 468 ms'],
    ],
    lead: '同一次逐路候选缓存上比较六种召回配置，并用产品管线逐题复核 Top10 结果。',
    points: ['三路加权的 Recall@10 最高（0.8652），为产品默认配置。', '稠密 + BM25 在 Recall@1、nDCG@10、MRR@10 上略高。', '三路 RRF 明显低于加权融合；产品 Top10 与离线结果逐题对账一致。'],
    env: [...SCIFACT_ENV, ['融合', '三路加权 0.70 / 0.15 / 0.15 · RRF k=60'], ['延迟', '顺序请求 · P50 211 ms · P95 468 ms']],
    chart: { legend: ['Recall@10'], groups: R10_CONFIGS.map((c) => ({ label: c.label, values: [c.value] })) },
    limits: ['延迟为顺序请求下的测量值，并发场景需另行压测。', '只评检索，不涉及回答生成质量。'],
    command: 'scripts/benchmarks/run_scifact.sh',
  },
  {
    id: 'blind-v5',
    rawUrl: raw('blind-v5'),
    version: 'v2026.07',
    date: '2026-07-28',
    title: 'Blind v5 生产契约验收',
    desc: 'LambdaMART v3 + 短词回退，对照 weighted score',
    type: 'LambdaMART',
    dataset: '750 题 · 10,299 chunks',
    key: 'MRR 92.16% → 95.64%',
    cols: ['LambdaMART v3', 'weighted score'],
    metrics: [['MRR', '95.64%', '92.16%', '+3.48']],
    config: [
      ['规模', '750 题 · 10,299 chunks'],
      ['排序', 'LambdaMART v3 + 短词回退'],
      ['对照', 'weighted score'],
    ],
    lead: '按生产契约口径做盲测验收：LambdaMART v3 加短词回退，对照 weighted score。',
    points: ['MRR 从 92.16% 提升到 95.64%。', '短词查询回退到 weighted score，避免特征不足时排序退化。'],
    env: [
      ['规模', '750 题 · 10,299 chunks'],
      ['排序', 'LambdaMART v3 + 短词回退'],
    ],
    chart: { legend: ['weighted score', 'LambdaMART v3'], groups: [{ label: 'MRR', values: [0.9216, 0.9564] }] },
    limits: ['盲测题集与 SciFact 不同，数字不可与 R10–R13 直接比较。'],
  },
  {
    id: 'blind-v4',
    rawUrl: raw('blind-v4'),
    version: 'v2026.07',
    date: '2026-07-24',
    title: 'Blind v4 最终验收',
    desc: '固定 Hybrid → LambdaMART v2',
    type: 'LambdaMART',
    dataset: 'C-MTEB T2Retrieval · 750 题',
    key: 'MRR 90.41% → 98.02%',
    cols: ['LambdaMART v2', '固定 Hybrid'],
    metrics: [['MRR', '98.02%', '90.41%', '+7.61']],
    config: [
      ['数据集', 'C-MTEB T2Retrieval · 750 题'],
      ['对照', '固定 Hybrid'],
      ['排序', 'LambdaMART v2'],
    ],
    lead: '在 C-MTEB T2Retrieval 750 题上，比较固定 Hybrid 与 LambdaMART v2。',
    points: ['MRR 从 90.41% 提升到 98.02%。'],
    env: [['数据集', 'C-MTEB T2Retrieval · 750 题']],
    chart: { legend: ['固定 Hybrid', 'LambdaMART v2'], groups: [{ label: 'MRR', values: [0.9041, 0.9802] }] },
    limits: ['数据集与 SciFact 不同，数字不可与 R10–R13 直接比较。'],
  },
  {
    id: 'r09',
    rawUrl: raw('r09'),
    version: 'v2026.07',
    date: '2026-07-05',
    title: 'R09 · 多路召回正式对照',
    desc: '仅稠密 / 稠密+BM25 / 三路，clean run',
    type: '四域基线',
    dataset: '四域 394 题 · 3,200 chunks',
    key: 'R@10 0.9725 · MRR 0.9216',
    cols: ['三路融合', '仅稠密'],
    metrics: [
      ['Recall@1', '0.6507', '0.6393', '+1.14'],
      ['Recall@10', '0.9725', '0.9745', '−0.20'],
      ['MRR', '0.9216', '0.9178', '+0.38'],
    ],
    config: [
      ['数据集', 'combined_4domain_clean'],
      ['规模', '394 题 · 3,200 chunks'],
      ['融合', 'weighted_score · 0.8 / 0.1 / 0.1'],
    ],
    lead: '仅稠密向量、稠密 + BM25、三路融合，在同一份 394 题数据上的正式 clean 运行。',
    points: [
      '三种配置的 Recall@10 都在 97% 以上，彼此相差不到 0.3 个百分点。',
      '三路融合的 Recall@1（0.6507）和 MRR（0.9216）最高：最相关的片段更常排在第一位。',
      '稠密 + BM25 的 Recall@10 和 nDCG@10 略高于三路融合，差距在误差范围内。',
    ],
    env: [
      ['数据集', 'combined_4domain_clean · ecom / video / dureader / cmedqa 公开子集'],
      ['规模', '394 条文档级查询 · 每域 800 chunks，共 3,200'],
      ['标注', '沿用原数据集正例'],
      ['召回深度', 'Dense Top150 · Sparse Top50 · BM25 Top50'],
      ['融合', 'weighted_score · 权重 0.8 / 0.1 / 0.1 · 最终 Top10'],
      ['阈值', 'Dense 0.30 · Sparse 0.40'],
      ['BM25', 'Qdrant sparse collection + IDF modifier'],
      ['运行状态', 'failed_sources = 0 · zero_ranked = 0'],
    ],
    chart: {
      legend: ['仅稠密向量', '稠密 + BM25', '三路融合'],
      groups: [
        { label: 'Recall@1', values: [0.639, 0.648, 0.651] },
        { label: 'Recall@5', values: [0.92, 0.917, 0.917] },
        { label: 'Recall@10', values: [0.9745, 0.975, 0.9725] },
        { label: 'nDCG@10', values: [0.922, 0.925, 0.924] },
        { label: 'MRR', values: [0.9178, 0.921, 0.9216] },
      ],
    },
    limits: ['相关性标注沿用原数据集，可能存在漏标；逐题结果中未命中的题目可人工复核。', '3,200 chunks 规模较小，语料扩大后召回会下降（见「语料规模 800 vs 2000」报告）。', '本报告只评检索，不涉及回答生成质量。'],
    command: 'linkrag-eval run --config reports/2026-07-05/route-3way.yaml --precheck',
  },
  {
    id: 'fusion',
    rawUrl: raw('fusion'),
    version: 'v2026.07',
    date: '2026-07-02',
    title: '融合策略对照',
    desc: 'RRF vs weighted_score，同候选复算',
    type: '四域基线',
    dataset: '四域 394 题',
    key: 'R@10 0.9715 → 0.9745',
    cols: ['weighted_score', 'RRF'],
    metrics: [['Recall@10', '0.9745', '0.9715', '+0.30']],
    config: [
      ['数据集', '四域 394 题'],
      ['对照', 'RRF vs weighted_score，同一批候选复算'],
    ],
    lead: '在同一批召回候选上分别用 RRF 与 weighted_score 融合，比较最终 Top10。',
    points: ['weighted_score 的 Recall@10 为 0.9745，RRF 为 0.9715。'],
    env: [['数据集', '四域 394 题']],
    chart: { legend: ['RRF', 'weighted_score'], groups: [{ label: 'Recall@10', values: [0.9715, 0.9745] }] },
    limits: ['旧四域小语料，数字只在同组内可比。'],
  },
  {
    id: 'corpus-size',
    version: 'v2026.06',
    date: '2026-06-22',
    title: '语料规模 800 vs 2000',
    desc: '每域 chunk 数提升 2.5 倍',
    type: '四域基线',
    dataset: '四域 394 题 · 8,000 chunks',
    key: 'R@10 0.9245 → 0.9013',
    cols: ['2000 / 域', '800 / 域'],
    metrics: [['Recall@10', '0.9013', '0.9245', '−2.32']],
    config: [
      ['数据集', '四域 394 题'],
      ['规模', '每域 800 → 2000 chunks，共 8,000'],
    ],
    lead: '把每域 chunk 数从 800 提升到 2000，观察语料扩大对召回的影响。',
    points: ['Recall@10 从 0.9245 降到 0.9013：干扰项增多后召回下降。'],
    env: [['数据集', '四域 394 题 · 8,000 chunks']],
    chart: { legend: ['800 / 域', '2000 / 域'], groups: [{ label: 'Recall@10', values: [0.9245, 0.9013] }] },
    limits: ['旧四域小语料，数字只在同组内可比。'],
  },
  {
    id: 'two-vs-three',
    version: 'v2026.06',
    date: '2026-06-20',
    title: '两路 vs 三路召回',
    desc: '加入稠密向量的消融',
    type: '四域基线',
    dataset: '500 题公开集',
    key: 'R@10 0.851 → 0.932',
    cols: ['三路', '两路'],
    metrics: [['Recall@10', '0.932', '0.851', '+8.10']],
    config: [['数据集', '500 题公开集']],
    lead: '在两路（稀疏 + BM25）基础上加入稠密向量，比较召回。',
    points: ['加入稠密向量后 Recall@10 从 0.851 提升到 0.932。'],
    env: [['数据集', '500 题公开集']],
    chart: { legend: ['两路', '三路'], groups: [{ label: 'Recall@10', values: [0.851, 0.932] }] },
    limits: ['早期实验，数据集与后续轮次不同。'],
  },
  {
    id: 'sparse-models',
    version: 'v2026.06',
    date: '2026-06-20',
    title: '稀疏模型对照',
    desc: 'BGE-M3 vs Doubao sparse',
    type: '四域基线',
    dataset: '360 题公开集',
    key: 'R@10 0.934 vs 0.905',
    cols: ['BGE-M3', 'Doubao sparse'],
    metrics: [['Recall@10', '0.934', '0.905', '+2.90']],
    config: [['数据集', '360 题公开集']],
    lead: '在同一份 360 题公开集上比较两种稀疏向量模型。',
    points: ['BGE-M3 的 Recall@10 为 0.934，Doubao sparse 为 0.905。'],
    env: [['数据集', '360 题公开集']],
    chart: { legend: ['Doubao sparse', 'BGE-M3'], groups: [{ label: 'Recall@10', values: [0.905, 0.934] }] },
    limits: ['早期实验，数据集与后续轮次不同。'],
  },
];

export const findReport = (id?: string) => REPORTS.find((r) => r.id === id);

/** 同类报告：同类型、按时间倒序，排除自身 */
export const relatedReports = (r: Report) => REPORTS.filter((x) => x.type === r.type && x.id !== r.id).slice(0, 3);

export const reproCommand = (r: Report) => (r.command ? `$ ${r.command}` : `# 见 ${GITHUB_URL}`);

/* ---------------- 复现指南 ---------------- */

export const REPRO_FACTS: [string, string][] = [
  ['数据集', 'BEIR SciFact 官方包 · MD5 5f7d1de6…'],
  ['LinkRag 版本', 'toLink-Rag 861f248 · Eval 0de8488'],
  ['对比版本', 'WeKnora 3e8b0bf · 隔离 Docker'],
  ['统计方法', '300 题配对 bootstrap · 10,000 次 · seed 20260929'],
];

/** 代码卡三个标签；tone：c 注释 / i 命令 / ok 成功 / o 普通输出 */
export type CodeLine = [tone: 'c' | 'i' | 'ok' | 'o', text: string];
export const CODE_TABS: { id: string; label: string; mono?: boolean; lines: CodeLine[] }[] = [
  {
    id: 'term',
    label: '终端',
    lines: [
      ['c', '# R10 · 准备数据、入库、三路消融与产品复核'],
      ['i', '$ scripts/benchmarks/run_scifact.sh'],
      ['o', ''],
      ['c', '# R11 · LambdaMART 训练与离线重排'],
      ['i', '$ scripts/benchmarks/run_scifact_lambdamart.sh fit-evaluate'],
      ['o', ''],
      ['c', '# R12 · WeKnora 同口径对比'],
      ['i', '$ python scripts/benchmarks/weknora_scifact.py evaluate'],
      ['o', ''],
      ['c', '# R13 · 前 30 chunk 文本重排'],
      ['i', '$ python scripts/benchmarks/rerank_scifact_top30.py --summarize'],
    ],
  },
  {
    id: 'config',
    label: 'config.yaml',
    mono: true,
    lines: [
      ['o', 'dataset: beir/scifact'],
      ['o', 'split: test          # 300 题'],
      ['o', 'routes: [dense, sparse, bm25]'],
      ['o', 'weights: [0.70, 0.15, 0.15]'],
      ['o', 'rerank:'],
      ['o', '  model: qwen3.7-text-rerank'],
      ['o', '  input_top_n: 30'],
    ],
  },
  {
    id: 'out',
    label: '输出',
    lines: [
      ['ok', '✓ 600 条重排响应 · sources_sha256 校验通过'],
      ['o', '  LinkRag  R@10 0.9020  nDCG@10 0.7889'],
      ['o', '  WeKnora  R@10 0.8953  nDCG@10 0.7869'],
    ],
  },
];
