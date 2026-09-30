/**
 * 博客文章（设计稿「10 博客」L11 列表 / L12 文章详情）。
 * 线上文章来自后端 B9 公开接口（Markdown，解析见 markdown.ts，加载见 data.ts）；
 * 这里的 STATIC_POSTS 是 Mock 模式的演示数据，也可用 scripts/export-blog-md.ts 导出为 Markdown 导入后台。
 * 正文用结构化块描述，渲染见 BlogPostPage；行内 `code` 以等宽字体显示。
 */

export type Category = '评测' | '技术' | '实践' | '版本更新';
export const CATEGORIES: Category[] = ['评测', '技术', '实践', '版本更新'];

/** 分类色：文字 / 强调色、封面底色 */
export const CATEGORY_TONE: Record<Category, { fg: string; bg: string }> = {
  评测: { fg: '#9c6a3a', bg: '#f6f1e9' },
  技术: { fg: '#4f6b58', bg: '#eef1ee' },
  实践: { fg: '#56657a', bg: '#eef0f3' },
  版本更新: { fg: '#8a6a4f', bg: '#f4efe9' },
};

export type Block =
  | { t: 'p'; text: string }
  | { t: 'list'; items: string[]; ordered?: boolean }
  | { t: 'h'; level: number; text: string }
  | { t: 'quote'; text: string }
  | { t: 'hr' }
  | { t: 'setup'; rows: [string, string][] }
  | { t: 'bars'; legend: [string, string]; groups: { label: string; values: [number, number] }[]; caption: string }
  | { t: 'table'; head: string[]; rows: string[][]; caption?: string }
  | { t: 'callout'; label: string; text: string }
  | { t: 'code'; lang: string; lines: string[] }
  | { t: 'img'; src: string; alt: string };

export interface Section {
  id: string;
  title: string;
  blocks: Block[];
}

export interface Post {
  slug: string;
  title: string;
  lead: string;
  category: Category;
  date: string;
  updated?: string;
  author: string;
  tags: string[];
  series?: string;
  /** 封面大字与说明 */
  cover: { figure: string; caption?: string; image?: string };
  /** 文章头下方的关键数字（最多 3 个） */
  figures?: { label: string; value: string; note: string }[];
  sections: Section[];
  /** 对应评测报告：用于文末「本文数据」 */
  reportId?: string;
}

export interface Series {
  id: string;
  title: string;
  desc: string;
  /** 按时间正序 */
  slugs: string[];
}

/** 专题名称与简介；文章通过 front matter `series: <id>` 归入专题，未登记的 id 不展示 */
export const SERIES_META: Omit<Series, 'slugs'>[] = [
  { id: 'eval', title: '评测复盘', desc: 'R09–R13 每一轮的设计、结果与局限' },
  { id: 'tuning', title: '检索调优', desc: '融合权重、学习排序与评测口径' },
];

export const AUTHOR = { name: 'LinkRag 团队', bio: '负责检索评测与复现工具。所有评测脚本和已公开的原始结果都可以下载复核。' };

export const STATIC_POSTS: Post[] = [
  {
    slug: 'r13-rerank-top30',
    title: 'R13：前 30 个候选接文本重排，Recall@10 到 90.20%',
    lead: '同一重排模型下，LinkRag 与 WeKnora 的候选质量差异被进一步放大。这篇记录为什么先把召回做宽、再交给重排，以及 300 题配对检验的结果。',
    category: '评测',
    date: '2026-09-29',
    updated: '2026-09-30',
    author: AUTHOR.name,
    tags: ['重排', 'Recall', 'SciFact', 'WeKnora'],
    series: 'eval',
    cover: { figure: '90.20%', caption: 'Recall@10 · 接重排后' },
    figures: [
      { label: 'Recall@10 · 接重排后', value: '90.20%', note: '同条件下 WeKnora 为 89.53%' },
      { label: '重排带来的提升', value: '+3.68', note: '百分点；WeKnora 为 +2.58' },
      { label: '95% 区间下界', value: '+1.34', note: '[+1.34, +6.13] 全部为正' },
    ],
    reportId: 'r13',
    sections: [
      {
        id: 'background',
        title: '背景',
        blocks: [{ t: 'p', text: '重排模型只能在给定的候选里挑选。如果正确答案没有进入前 30，重排再强也无能为力。所以这一轮不比较“谁的重排更好”，而是让双方接同一个重排，只比较候选的质量。' }],
      },
      {
        id: 'setup',
        title: '实验设置',
        blocks: [
          {
            t: 'setup',
            rows: [
              ['数据集', 'BEIR SciFact · 5,183 篇文档 · 官方 test 300 题'],
              ['候选', '双方各取前 30 个 chunk，按源文档去重后计分'],
              ['重排模型', 'qwen3.7-text-rerank，双方调用参数相同'],
              ['计分口径', '源文档级 Recall@10 / nDCG@10 / MRR@10'],
            ],
          },
        ],
      },
      {
        id: 'results',
        title: '结果',
        blocks: [
          { t: 'p', text: '两边都从重排中获益，LinkRag 的提升更大：Recall@10 从 0.8652 到 0.9020，WeKnora 从 0.8696 到 0.8953。' },
          {
            t: 'bars',
            legend: ['重排前', '重排后'],
            groups: [
              { label: 'LinkRag 三路加权', values: [0.8652, 0.902] },
              { label: 'WeKnora 原生混合', values: [0.8696, 0.8953] },
            ],
            caption: '图 1　重排前后的 Recall@10，纵轴从 0 开始。',
          },
          {
            t: 'table',
            head: ['系统', '重排前', '重排后', '提升'],
            rows: [
              ['LinkRag 三路加权', '0.8652', '0.9020', '+3.68'],
              ['WeKnora 原生混合', '0.8696', '0.8953', '+2.58'],
            ],
          },
          { t: 'callout', label: '结论', text: '前 30 个候选覆盖了 93.77% 的相关文档（WeKnora 为 93.10%）。候选更全，重排才有更多正确答案可挑。' },
        ],
      },
      {
        id: 'why',
        title: '为什么差距被放大',
        blocks: [
          {
            t: 'p',
            text: 'LinkRag 的候选来自稠密、稀疏、BM25 三路 `weighted_score` 融合。单看原生检索，双方 Recall@10 几乎持平；但在第 11–30 名这段“备选区”，LinkRag 保留了更多相关文档，重排正好把它们提上来。',
          },
        ],
      },
      {
        id: 'limits',
        title: '局限',
        blocks: [
          {
            t: 'list',
            items: ['重排在隔离脚本中完成，尚未接入产品管线，线上延迟需另行评估。', 'SciFact 是英文科学文献，中文与长文档场景需要单独验证。', '两边调用同一重排接口，结果受该模型版本影响。'],
          },
        ],
      },
      {
        id: 'repro',
        title: '复现',
        blocks: [
          { t: 'p', text: '脚本会读取双方的候选缓存，调用重排接口并输出汇总指标与逐题变化：' },
          { t: 'code', lang: 'bash', lines: ['# 先完成 R10 的候选缓存，再运行重排汇总', '$ scripts/benchmarks/run_scifact.sh', '$ python scripts/benchmarks/rerank_scifact_top30.py --summarize'] },
        ],
      },
    ],
  },
  {
    slug: 'r12-weknora-native',
    title: 'R12：对比 WeKnora 原生检索',
    lead: '隔离部署 WeKnora，导入同样的 5,183 篇文档、使用同名稠密模型，按源文档用同一套公式评分。原生检索阶段，LinkRag 的相关文档更早出现在前 5 条结果里。',
    category: '评测',
    date: '2026-09-29',
    author: AUTHOR.name,
    tags: ['WeKnora', 'Recall', 'SciFact'],
    series: 'eval',
    cover: { figure: '+2.37', caption: 'Recall@5 · 原生检索' },
    figures: [
      { label: 'Recall@5', value: '0.7991', note: 'WeKnora 为 0.7754' },
      { label: 'Hit Rate@5', value: '0.8133', note: 'WeKnora 为 0.7967' },
      { label: 'Recall@100', value: '0.9633', note: 'WeKnora 为 0.9567' },
    ],
    reportId: 'r12',
    sections: [
      {
        id: 'background',
        title: '背景',
        blocks: [{ t: 'p', text: '开源 RAG 项目很多，但很少有人在同一份语料、同一套计分口径下把检索结果摆在一起。这一轮选择 WeKnora（腾讯开源）作为第一个对照对象，只比较检索，不涉及回答生成。' }],
      },
      {
        id: 'setup',
        title: '实验设置',
        blocks: [
          {
            t: 'setup',
            rows: [
              ['数据集', 'BEIR SciFact · 5,183 篇文档 · 官方 test 300 题'],
              ['稠密模型', '双方均为 text-embedding-v4 · 1024 维'],
              ['WeKnora', '3e8b0bf · 隔离 Docker · 默认两路 RRF k=60'],
              ['计分口径', '源文档级：同一文档的多个 chunk 只计一次'],
            ],
          },
        ],
      },
      {
        id: 'results',
        title: '结果',
        blocks: [
          {
            t: 'table',
            head: ['指标', 'LinkRag', 'WeKnora', '差值'],
            rows: [
              ['Recall@5', '0.7991', '0.7754', '+2.37'],
              ['Hit Rate@5', '0.8133', '0.7967', '+1.66'],
              ['Recall@100', '0.9633', '0.9567', '+0.66'],
              ['MRR@10', '0.7037', '0.6990', '+0.47'],
            ],
            caption: '差值单位为百分点。',
          },
          { t: 'callout', label: '结论', text: '差距主要体现在前 5 条：相关文档更早出现，意味着把结果交给大模型时，上下文里的有效信息更多。' },
        ],
      },
      {
        id: 'limits',
        title: '局限',
        blocks: [{ t: 'list', items: ['WeKnora 使用默认的两路 RRF 配置，未针对 SciFact 调参。', '只评检索，不涉及回答生成质量。'] }],
      },
      {
        id: 'repro',
        title: '复现',
        blocks: [{ t: 'code', lang: 'bash', lines: ['# 需先按文档部署隔离的 WeKnora 实例', '$ python scripts/benchmarks/weknora_scifact.py evaluate'] }],
      },
    ],
  },
  {
    slug: 'r11-lambdamart',
    title: 'LambdaMART 离线实验：9 题变好、2 题变差',
    lead: '学习排序能带来多少增益、代价是什么，以及它为什么还没有上线。',
    category: '技术',
    date: '2026-09-29',
    author: AUTHOR.name,
    tags: ['LambdaMART', 'Recall', 'SciFact'],
    series: 'eval',
    cover: { figure: '+1.90', caption: 'Recall@10 · 离线重排' },
    figures: [
      { label: 'Recall@10', value: '0.8842', note: '三路加权为 0.8652' },
      { label: '提升', value: '+1.90', note: '百分点' },
      { label: '逐题变化', value: '9 / 2', note: '300 题中改善 9 题、变差 2 题' },
    ],
    reportId: 'r11',
    sections: [
      {
        id: 'setup',
        title: '实验设置',
        blocks: [
          { t: 'p', text: '用 SciFact train 集 809 题训练 LambdaMART，在三路加权召回的候选上做离线重排；test 300 题只用于评测，不参与训练。' },
          {
            t: 'setup',
            rows: [
              ['训练集', 'SciFact train · 809 题'],
              ['评测集', 'SciFact test · 300 题'],
              ['候选', '三路加权召回结果'],
              ['排序模型', 'LambdaMART'],
            ],
          },
        ],
      },
      {
        id: 'results',
        title: '结果',
        blocks: [
          { t: 'p', text: 'Recall@10 从 0.8652 提升到 0.8842，提升 1.90 个百分点。逐题看，9 题改善、2 题变差，其余不变。' },
          {
            t: 'bars',
            legend: ['三路加权', '+ LambdaMART'],
            groups: [{ label: 'Recall@10', values: [0.8652, 0.8842] }],
            caption: '图 1　离线重排前后的 Recall@10，纵轴从 0 开始。',
          },
        ],
      },
      {
        id: 'why-not-yet',
        title: '为什么还没有上线',
        blocks: [
          {
            t: 'list',
            items: ['训练与评测来自同一数据集的不同划分，跨领域泛化需另行验证。', '同一批候选接文本重排（R13）的提升更大，两者的取舍需要结合线上延迟一起评估。'],
          },
        ],
      },
      {
        id: 'repro',
        title: '复现',
        blocks: [{ t: 'code', lang: 'bash', lines: ['$ scripts/benchmarks/run_scifact_lambdamart.sh fit-evaluate'] }],
      },
    ],
  },
  {
    slug: 'r10-three-route-ablation',
    title: '三路混合检索：六种召回配置的消融',
    lead: '仅稠密、仅稀疏、仅 BM25、两两组合和三路融合，在同一次候选缓存上比较，并用产品管线逐题复核 Top10。',
    category: '技术',
    date: '2026-09-29',
    author: AUTHOR.name,
    tags: ['BM25', 'Recall', 'SciFact', '融合'],
    series: 'eval',
    cover: { figure: '3 路', caption: '0.70 / 0.15 / 0.15' },
    figures: [
      { label: 'Recall@10 · 三路加权', value: '0.8652', note: '六种配置中最高' },
      { label: '检索 P50', value: '211 ms', note: 'P95 468 ms · 顺序请求' },
      { label: '对比仅稠密', value: '+1.43', note: '百分点' },
    ],
    reportId: 'r10',
    sections: [
      {
        id: 'setup',
        title: '实验设置',
        blocks: [
          {
            t: 'setup',
            rows: [
              ['数据集', 'BEIR SciFact · 5,183 篇文档 · 官方 test 300 题'],
              ['三路权重', '稠密 0.70 · 稀疏 0.15 · BM25 0.15'],
              ['RRF', 'k = 60'],
              ['复核', '产品管线 Top10 与离线结果逐题对账'],
            ],
          },
        ],
      },
      {
        id: 'results',
        title: '结果',
        blocks: [
          {
            t: 'table',
            head: ['召回配置', 'Recall@10'],
            rows: [
              ['仅稀疏', '0.7046'],
              ['仅 BM25', '0.7543'],
              ['三路 RRF', '0.8106'],
              ['仅稠密', '0.8509'],
              ['稠密 + BM25', '0.8609'],
              ['三路加权（产品默认）', '0.8652'],
            ],
          },
          { t: 'callout', label: '结论', text: '三路加权的 Recall@10 最高，为产品默认配置；三路 RRF 明显低于加权融合。稠密 + BM25 在 Recall@1、nDCG@10、MRR@10 上略高。' },
        ],
      },
      {
        id: 'latency',
        title: '延迟',
        blocks: [{ t: 'p', text: '产品 Top10 检索在顺序请求下 P50 为 211 ms、P95 为 468 ms。并发场景需另行压测。' }],
      },
      {
        id: 'repro',
        title: '复现',
        blocks: [{ t: 'code', lang: 'bash', lines: ['# 准备数据、入库、三路消融与产品复核', '$ scripts/benchmarks/run_scifact.sh'] }],
      },
    ],
  },
  {
    slug: 'source-document-scoring',
    title: '为什么按源文档计分，而不是按 chunk',
    lead: 'chunk 级指标会高估召回；源文档级口径更接近用户的真实感受。',
    category: '评测',
    date: '2026-09-28',
    author: AUTHOR.name,
    tags: ['评测口径', '分块', 'Recall'],
    series: 'tuning',
    cover: { figure: '源文档' },
    sections: [
      {
        id: 'problem',
        title: '问题',
        blocks: [
          { t: 'p', text: '一篇文档切分成多个 chunk 后，同一篇文档可能在 Top10 里出现好几次。如果按 chunk 计分，这几次命中会被重复计算，Recall 看起来更高，但用户实际拿到的相关文档并没有变多。' },
        ],
      },
      {
        id: 'rule',
        title: '我们的口径',
        blocks: [
          {
            t: 'list',
            items: ['同一源文档的多个 chunk 只计一次，按首次出现的排名计分。', '相关性标注沿用数据集原始的文档级正例，不做额外改写。', '`ndcg_binary@10` 使用二值相关度，与 BEIR 官方计分保持可比。'],
          },
        ],
      },
      {
        id: 'impact',
        title: '对结果的影响',
        blocks: [
          { t: 'p', text: '按源文档计分后，不同分块大小之间的比较更公平：切得越碎，并不会因此“多命中”。评测中心 R10–R13 的全部数字都采用这一口径。' },
        ],
      },
    ],
  },
  {
    slug: 'r09-four-domain-baseline',
    title: 'R09：多路召回正式对照（旧四域基线）',
    lead: '仅稠密向量、稠密 + BM25、三路融合，在同一份 394 题数据上的正式 clean 运行。',
    category: '评测',
    date: '2026-07-05',
    author: AUTHOR.name,
    tags: ['BM25', 'Recall', '融合'],
    series: 'eval',
    cover: { figure: '0.9216', caption: 'MRR · 三路融合' },
    figures: [
      { label: 'Recall@1 · 三路融合', value: '0.6507', note: '仅稠密为 0.6393' },
      { label: 'MRR · 三路融合', value: '0.9216', note: '仅稠密为 0.9178' },
      { label: 'Recall@10 · 三路融合', value: '0.9725', note: '仅稠密为 0.9745' },
    ],
    reportId: 'r09',
    sections: [
      {
        id: 'setup',
        title: '实验设置',
        blocks: [
          {
            t: 'setup',
            rows: [
              ['数据集', 'combined_4domain_clean · 394 题'],
              ['规模', '每域 800 chunks，共 3,200'],
              ['融合', 'weighted_score · 0.8 / 0.1 / 0.1 · 最终 Top10'],
            ],
          },
        ],
      },
      {
        id: 'results',
        title: '结果',
        blocks: [
          {
            t: 'table',
            head: ['指标', '三路融合', '仅稠密', '差值'],
            rows: [
              ['Recall@1', '0.6507', '0.6393', '+1.14'],
              ['Recall@10', '0.9725', '0.9745', '−0.20'],
              ['MRR', '0.9216', '0.9178', '+0.38'],
            ],
            caption: '差值单位为百分点。',
          },
          { t: 'p', text: '三种配置的 Recall@10 都在 97% 以上，彼此相差不到 0.3 个百分点；三路融合的 Recall@1 和 MRR 最高，最相关的片段更常排在第一位。' },
        ],
      },
      {
        id: 'limits',
        title: '局限',
        blocks: [{ t: 'list', items: ['3,200 chunks 规模较小，语料扩大后召回会下降。', '数据集与 R10–R13 不同，数字只在同组内可比。'] }],
      },
    ],
  },
];

/** 按日期倒序（同日按原顺序） */
export const sortPosts = (posts: Post[]) => [...posts].sort((a, b) => b.date.localeCompare(a.date));

/** 由文章的 series 字段生成专题（按时间正序）；静态数据额外带上跨专题的历史归类 */
export function buildSeries(posts: Post[]): Series[] {
  return SERIES_META.map((m) => ({
    ...m,
    slugs: sortPosts(posts.filter((p) => p.series === m.id || EXTRA_SERIES[m.id]?.includes(p.slug)))
      .reverse()
      .map((p) => p.slug),
  })).filter((s) => s.slugs.length > 0);
}
/** 静态演示数据中同时属于多个专题的文章 */
const EXTRA_SERIES: Record<string, string[]> = { tuning: ['r10-three-route-ablation', 'r11-lambdamart'] };

/** 正文纯文本，用于阅读时长与搜索 */
export function postText(p: Post) {
  const parts: string[] = [p.title, p.lead];
  for (const s of p.sections) {
    parts.push(s.title);
    for (const b of s.blocks) {
      if (b.t === 'p') parts.push(b.text);
      else if (b.t === 'list') parts.push(...b.items);
      else if (b.t === 'callout' || b.t === 'quote' || b.t === 'h') parts.push(b.text);
      else if (b.t === 'setup') parts.push(...b.rows.flat());
      else if (b.t === 'table') parts.push(...b.head, ...b.rows.flat());
    }
  }
  return parts.join(' ');
}

/** 阅读时长：中文约 400 字 / 分钟，至少 1 分钟 */
export const readMinutes = (p: Post) => Math.max(1, Math.round(postText(p).length / 400));

/** 博客数据集：列表（倒序）+ 专题；详情页的上下篇与相关推荐都基于它 */
export interface BlogData {
  posts: Post[];
  series: Series[];
}

export function makeBlogData(posts: Post[]): BlogData {
  return { posts: sortPosts(posts), series: buildSeries(posts) };
}

/** 同专题的上一篇 / 下一篇（取文章所属的第一个专题） */
export function neighbors(data: BlogData, p: Post) {
  const s = data.series.find((x) => x.slugs.includes(p.slug) && (x.id === p.series || !p.series));
  if (!s) return { series: undefined, index: -1, prev: undefined, next: undefined };
  const find = (slug?: string) => data.posts.find((x) => x.slug === slug);
  const i = s.slugs.indexOf(p.slug);
  return { series: s, index: i, prev: find(s.slugs[i - 1]), next: find(s.slugs[i + 1]) };
}

/** 继续阅读：同标签优先，其次最新，排除自身，取 2 篇 */
export function relatedPosts(data: BlogData, p: Post, n = 2) {
  const score = (x: Post) => x.tags.filter((t) => p.tags.includes(t)).length;
  return data.posts
    .filter((x) => x.slug !== p.slug)
    .map((x, i) => ({ x, s: score(x), i }))
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .slice(0, n)
    .map((r) => r.x);
}

/** 全部标签，按出现次数排序 */
export function allTags(posts: Post[]) {
  const count = new Map<string, number>();
  for (const p of posts) for (const t of p.tags) count.set(t, (count.get(t) ?? 0) + 1);
  return [...count.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
}
