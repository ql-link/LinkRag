/**
 * Hero 演示动画的时间线（28s 循环）。
 *
 * 画面是一张「世界画布」，镜头（camera）在上面平移和缩放：
 *   拖入文件（镜头跟随）→ 扫描识别标题 / 表格，切块飞进知识库星图，写入双索引 →
 *   在输入框里提问（镜头跟随光标）→ 问题化作查询节点，三路检索波纹点亮分块 →
 *   候选飞进重排面板、按分数重新排序，留下 Top 5 →
 *   流式回答 → 引用 [3] 连回刚上传文件的原文 → 拉远全景收尾。
 *
 * 所有画面状态都由 getHeroFrame(t) 从时间推导，组件只负责渲染。
 */

export const HERO_DURATION = 28;

export const heroSegments = [
  {
    id: 'upload',
    label: '上传',
    title: '多格式文档导入',
    desc: '支持 PDF、DOCX、Markdown、XLSX 等格式，拖拽即可导入知识库',
    start: 0,
    end: 3.5,
  },
  {
    id: 'parse',
    label: '解析',
    title: '结构化解析与分块',
    desc: '识别标题层级、表格与正文，按语义切成分块，同时写入向量与关键词索引',
    start: 3.5,
    end: 8,
  },
  { id: 'ask', label: '提问', title: '自然语言提问', desc: '不用想关键词，直接描述你的问题', start: 8, end: 11 },
  {
    id: 'retrieve',
    label: '检索',
    title: '三路混合检索',
    desc: '语义向量、稀疏向量、关键词三路召回，汇总出 28 段候选',
    start: 11,
    end: 14,
  },
  {
    id: 'rerank',
    label: '重排',
    title: '精排重排序',
    desc: '重排模型逐段打分，把真正相关的 5 段排到最前面',
    start: 14,
    end: 17,
  },
  { id: 'answer', label: '回答', title: '引用式回答生成', desc: '流式生成，每个结论都标注出处', start: 17, end: 23 },
  {
    id: 'trace',
    label: '溯源',
    title: '原文溯源',
    desc: '引用直达原文段落，刚上传的文件也能立刻被引用',
    start: 23,
    end: 28,
  },
] as const;

export type HeroSegmentId = (typeof heroSegments)[number]['id'];

/** 收尾全景的字幕与功能标签。 */
export const heroClosing = { title: '每一句回答，都有出处', desc: '开源 RAG 知识库 · 可私有化部署' } as const;
export const heroFeatures = ['PDF · DOCX · MD · XLSX', '三路混合检索 + 重排', '引用可溯源'] as const;
const CLOSING_AT = 26.3;

/** 开启 prefers-reduced-motion 时展示的静态帧：回答完成、引用 [3] 溯源到原文。 */
export const HERO_STATIC_TIME = 25.5;

// ---------------------------------------------------------------------------
// 内容
// ---------------------------------------------------------------------------

export const heroExistingFiles = [
  { type: 'PDF', name: '产品规划.pdf', chunks: 412 },
  { type: 'DOCX', name: '技术说明.docx', chunks: 398 },
  { type: 'XLSX', name: '客服问答.xlsx', chunks: 232 },
] as const;

export const heroNewFile = { type: 'MD', name: '上线方案.md', size: '36 KB', chunks: 244 } as const;

export const HERO_BASE_CHUNKS = heroExistingFiles.reduce((sum, f) => sum + f.chunks, 0);

export const heroQuestion = 'Q3 上线方案里，产品目标和技术约束冲突时怎么处理？';

export const heroAnswerIntro = '根据《上线方案》和《产品规划》，建议分三步处理：';

export const heroAnswerItems = [
  { lead: '分阶段交付', text: '：先保证核心场景可用，性能指标放到二期。', cite: 1 },
  { lead: '增量同步', text: '：文档变更只重建受影响的分块，避免全量重跑。', cite: 2 },
  { lead: '可回滚发布', text: '：每次发布记录索引版本，出问题可回退到上一版。', cite: 3 },
] as const;

export const heroSources = [
  { id: 1, type: 'PDF', file: '产品规划.pdf', loc: 'p.3', score: '0.92', fresh: false },
  { id: 2, type: 'DOCX', file: '技术说明.docx', loc: 'p.12', score: '0.88', fresh: false },
  { id: 3, type: 'MD', file: '上线方案.md', loc: '§2.3', score: '0.86', fresh: true },
] as const;

export const heroExcerpt = {
  before: '发布流程：',
  mark: '每次发布记录索引版本号，出现问题时可一键回滚到上一版本。',
} as const;

export const heroLanes = [
  { label: '语义向量', color: '#c8925a', start: 11.45 },
  { label: '稀疏向量', color: '#7f9c86', start: 11.8 },
  { label: '关键词', color: '#7d8fb0', start: 12.15 },
] as const;

/** 文档卡片里的版面结构（y 为卡片内坐标），扫描线经过时依次打上标签。 */
export const heroDocLines = [
  { kind: 'h1', y: 64, h: 9, w: 0.62, tag: 'H1' },
  { kind: 'p', y: 84, h: 6, w: 0.92, tag: null },
  { kind: 'p', y: 99, h: 6, w: 0.8, tag: null },
  { kind: 'h2', y: 118, h: 8, w: 0.5, tag: 'H2' },
  { kind: 'p', y: 136, h: 6, w: 0.88, tag: null },
  { kind: 'table', y: 152, h: 30, w: 1, tag: '表格' },
  { kind: 'h2', y: 194, h: 8, w: 0.46, tag: 'H2' },
  { kind: 'p', y: 212, h: 6, w: 0.84, tag: null },
  { kind: 'p', y: 227, h: 6, w: 0.6, tag: null },
] as const;

// ---------------------------------------------------------------------------
// 世界坐标（px）
// ---------------------------------------------------------------------------

export const WORLD_W = 1320;
export const WORLD_H = 740;

export const KB = { x: 300, y: 150, w: 520, h: 300 };
export const DOC = { x: 60, y: 175, w: 200, h: 260 };
export const INPUT = { x: 300, y: 490, w: 520, h: 56 };
export const ANSWER = { x: 880, y: 130, w: 400, h: 430 };
export const RERANK = { x: 880, y: 150, w: 400, head: 56, rowH: 30, foot: 40 };
export const EXCERPT = { x: 330, y: 490, w: 440, h: 124 };

export const FILE_START = { x: 200, y: 580 };
export const DROP = { x: 560, y: 300 };
export const SEND = { x: INPUT.x + INPUT.w - 30, y: INPUT.y + INPUT.h / 2 };
const CARET_X0 = INPUT.x + 20;
/** 问题文字在 15px 下的近似宽度，只用于镜头跟随光标。 */
const QUESTION_W = 363;

/** 知识库卡片底部的文件标签行。 */
export const KB_CHIP = { y: KB.y + KB.h - 32, x0: KB.x + 22, w: 114, gap: 8 };
export const kbChipCenter = (i: number) => ({
  x: KB_CHIP.x0 + i * (KB_CHIP.w + KB_CHIP.gap) + KB_CHIP.w / 2,
  y: KB_CHIP.y,
});

/** 回答卡片底部的三条来源行（中心 y）。 */
export const SOURCE_ROW_Y = [ANSWER.y + ANSWER.h - 84, ANSWER.y + ANSWER.h - 56, ANSWER.y + ANSWER.h - 28];
export const SOURCE_ROW_X = ANSWER.x + 16;

// 分块星图：20 × 8 = 160 个点，每个点代表一批分块。
export const GRID = { cols: 20, rows: 8, pitch: 22, dot: 10, x0: 351, y0: 227 };
export const TOTAL_DOTS = GRID.cols * GRID.rows;
/** 已有 3 个文件占 130 个点（1,042 / 1,286 ≈ 130 / 160），新文件填满剩下的 30 个。 */
export const EXISTING_DOTS = 130;
export const NEW_DOTS = TOTAL_DOTS - EXISTING_DOTS;

export const dotCenter = (i: number) => ({
  x: GRID.x0 + (i % GRID.cols) * GRID.pitch,
  y: GRID.y0 + Math.floor(i / GRID.cols) * GRID.pitch,
});

/** 每一路检索命中的点（互不重叠，合计 28）。 */
export const LANE_HITS: readonly (readonly number[])[] = [
  [3, 17, 24, 41, 58, 66, 87, 102, 131, 138, 146, 155],
  [9, 30, 45, 71, 79, 94, 113, 143, 150],
  [12, 36, 52, 99, 118, 135, 158],
];
export const HERO_CANDIDATES = LANE_HITS.reduce((sum, l) => sum + l.length, 0);

const laneOf = (i: number) => LANE_HITS.findIndex((l) => l.includes(i));

/**
 * 进入重排面板的 8 段候选，按融合分（初始顺序）排列。
 * 点号 ≥ 130 的属于刚上传的《上线方案.md》。
 */
const candidateBase = [
  { dot: 3, type: 'XLSX', file: '客服问答.xlsx', loc: '第 18 行', fused: 0.71, score: 0.41 },
  { dot: 45, type: 'DOCX', file: '技术说明.docx', loc: 'p.12', fused: 0.69, score: 0.88 },
  { dot: 146, type: 'MD', file: '上线方案.md', loc: '§2.3', fused: 0.66, score: 0.86 },
  { dot: 99, type: 'DOCX', file: '技术说明.docx', loc: 'p.4', fused: 0.64, score: 0.37 },
  { dot: 24, type: 'PDF', file: '产品规划.pdf', loc: 'p.3', fused: 0.61, score: 0.92 },
  { dot: 52, type: 'PDF', file: '产品规划.pdf', loc: 'p.7', fused: 0.58, score: 0.74 },
  { dot: 138, type: 'MD', file: '上线方案.md', loc: '§1.2', fused: 0.55, score: 0.79 },
  { dot: 113, type: 'XLSX', file: '客服问答.xlsx', loc: '第 3 行', fused: 0.52, score: 0.22 },
] as const;

const byScore = [...candidateBase].sort((a, b) => b.score - a.score);
export const heroCandidates = candidateBase.map((c) => ({
  ...c,
  lane: laneOf(c.dot),
  rank: byScore.indexOf(c),
}));
export const RERANK_H = RERANK.head + heroCandidates.length * RERANK.rowH + RERANK.foot;
export const rerankRowY = (pos: number) => RERANK.y + RERANK.head + pos * RERANK.rowH + RERANK.rowH / 2;

/** 重排后的 Top 5（按名次）；其中包含引用 [1]（产品规划）、[2]（技术说明）、[3]（上线方案）。 */
export const TOP5: readonly number[] = byScore.slice(0, 5).map((c) => c.dot);
export const CITE3_DOT = 146;
const candidateIndex = (i: number) => heroCandidates.findIndex((c) => c.dot === i);
const candFlightStart = (k: number) => 14.1 + k * 0.05;

const RING_SPEED = 300;
const RING_LIFE = 0.9;

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const clamp01 = (v: number) => clamp(v, 0, 1);
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
export const progress = (t: number, start: number, end: number) => clamp01((t - start) / (end - start));
export const ease = (v: number) => (v < 0.5 ? 4 * v * v * v : 1 - (-2 * v + 2) ** 3 / 2);
const between = (t: number, a: number, b: number) => t >= a && t < b;

type Key = { t: number; x: number; y: number; z: number };

function interp(keys: readonly Key[], t: number) {
  const next = keys.findIndex((k) => k.t > t);
  if (next === -1) return keys[keys.length - 1];
  if (next === 0) return keys[0];
  const a = keys[next - 1];
  const b = keys[next];
  const p = ease(progress(t, a.t, b.t));
  return { t, x: lerp(a.x, b.x, p), y: lerp(a.y, b.y, p), z: lerp(a.z, b.z, p) };
}

const cameraKeys: Key[] = [
  { t: 0, x: 250, y: 600, z: 1.75 },
  { t: 0.5, x: 250, y: 600, z: 1.75 },
  // 0.5–2.2 镜头跟随拖拽中的文件，见 getHeroFrame
  { t: 2.2, x: 560, y: 320, z: 1.4 },
  { t: 2.6, x: 560, y: 315, z: 1.4 },
  { t: 3.4, x: 480, y: 300, z: 1.1 },
  // 推近文档，看扫描识别结构
  { t: 4.1, x: 300, y: 300, z: 1.45 },
  { t: 5.0, x: 300, y: 305, z: 1.45 },
  // 跟着分块飞进知识库
  { t: 7.2, x: 480, y: 300, z: 1.2 },
  { t: 7.9, x: 560, y: 300, z: 1.25 },
  { t: 8.1, x: 560, y: 360, z: 1.15 },
  { t: 8.9, x: 430, y: INPUT.y + INPUT.h / 2, z: 2 },
  // 8.9–10.3 镜头跟随输入光标
  { t: 10.3, x: CARET_X0 + QUESTION_W - 60, y: INPUT.y + INPUT.h / 2, z: 2 },
  { t: 10.6, x: 700, y: INPUT.y + INPUT.h / 2, z: 1.85 },
  { t: 11.4, x: 560, y: 330, z: 1.1 },
  { t: 13.6, x: 560, y: 315, z: 1.18 },
  // 候选飞向重排面板：先拉开看全，再推近面板
  { t: 14.6, x: 880, y: 320, z: 1.0 },
  { t: 15.2, x: 1080, y: 330, z: 1.45 },
  { t: 16.6, x: 1080, y: 330, z: 1.5 },
  { t: 17.2, x: 1080, y: 360, z: 1.36 },
  { t: 22.8, x: 1080, y: 360, z: 1.42 },
  { t: 23.2, x: 1080, y: 360, z: 1.42 },
  { t: 24.1, x: 690, y: 480, z: 1.4 },
  { t: 25.8, x: 690, y: 485, z: 1.5 },
  { t: 26.8, x: 660, y: 370, z: 0.8 },
  { t: 28, x: 660, y: 370, z: 0.8 },
];

/** 全景机位：reduced-motion 静态帧和循环结尾都用它。 */
export const WIDE_CAMERA = { x: 660, y: 370, z: 0.8 };

const cursorKeys: Key[] = [
  { t: 0, x: 240, y: 590, z: 1 },
  { t: 0.5, x: 240, y: 590, z: 1 },
  // 0.5–2.2 光标跟随拖拽中的文件
  { t: 2.2, x: 600, y: 310, z: 1 },
  { t: 3.2, x: 700, y: 240, z: 1 },
  { t: 8.3, x: 700, y: 240, z: 1 },
  { t: 8.85, x: 340, y: 522, z: 1 },
  { t: 10.2, x: 700, y: 540, z: 1 },
  { t: 10.55, x: SEND.x + 2, y: SEND.y + 3, z: 1 },
  { t: 10.8, x: SEND.x + 2, y: SEND.y + 3, z: 1 },
  { t: 11.8, x: 830, y: 650, z: 1 },
  { t: 22.7, x: 1010, y: 650, z: 1 },
  { t: 23.45, x: SOURCE_ROW_X + 70, y: SOURCE_ROW_Y[2] + 2, z: 1 },
  { t: 28, x: SOURCE_ROW_X + 70, y: SOURCE_ROW_Y[2] + 2, z: 1 },
];

// 分块飞行：第 k 块（0–29）从文档飞向星图第 130+k 个点。
const CHUNK_START = 5.0;
const CHUNK_STAGGER = 0.065;
const CHUNK_FLIGHT = 0.55;
const chunkLandTime = (k: number) => CHUNK_START + k * CHUNK_STAGGER + CHUNK_FLIGHT;

function quad(a: { x: number; y: number }, c: { x: number; y: number }, b: { x: number; y: number }, p: number) {
  const q = 1 - p;
  return { x: q * q * a.x + 2 * q * p * c.x + p * p * b.x, y: q * q * a.y + 2 * q * p * c.y + p * p * b.y };
}

/** 拖拽文件的抛物线轨迹，p ∈ [0, 1]。 */
export function dragPoint(p: number) {
  return {
    x: lerp(FILE_START.x, DROP.x, p),
    y: lerp(FILE_START.y, DROP.y, p) - Math.sin(Math.PI * p) * 70,
  };
}

const distToDrop = (i: number) => {
  const c = dotCenter(i);
  return Math.hypot(c.x - DROP.x, c.y - DROP.y);
};

export type HeroDot = {
  present: boolean;
  fresh: boolean;
  /** 被哪一路检索点亮（0–2），未点亮为 -1。 */
  lane: number;
  /** 点亮强度 0–1。 */
  glow: number;
  top: boolean;
  /** 已飞去重排面板，星图里只留淡影。 */
  away: boolean;
};

/** 星图中第 i 个点在时刻 t 的状态。 */
export function dotState(i: number, rawTime: number): HeroDot {
  const t = ((rawTime % HERO_DURATION) + HERO_DURATION) % HERO_DURATION;
  const fresh = i >= EXISTING_DOTS;
  const present = !fresh || t >= chunkLandTime(i - EXISTING_DOTS);
  const top = TOP5.includes(i);
  const k = candidateIndex(i);
  const away = k !== -1 && between(t, candFlightStart(k), 17.2);
  const l = laneOf(i);
  let glow = 0;
  let lane = -1;

  if (l !== -1) {
    const litAt = heroLanes[l].start + distToDrop(i) / RING_SPEED;
    // 候选分块保持亮着，直到飞去重排面板；其余命中分块提前熄灭
    const end = k !== -1 ? candFlightStart(k) : 14.0;
    if (t >= litAt && t < end) {
      lane = l;
      const fadeOut = k !== -1 ? 1 : 1 - progress(t, 13.6, 14.0);
      glow = progress(t, litAt, litAt + 0.15) * fadeOut;
    }
  }
  // 写入索引时新分块依次闪一下
  if (fresh && between(t, 7.45, 7.95)) {
    const n = i - EXISTING_DOTS;
    glow = Math.max(glow, 1 - Math.abs(progress(t, 7.45, 7.95) * NEW_DOTS - n) / 6);
  }
  // 溯源时，被引用的原文分块在星图里亮起
  if (i === CITE3_DOT && t >= 24.3 && t < 27.4) {
    lane = 0;
    glow = Math.max(glow, progress(t, 24.3, 24.6));
  }
  return { present, fresh, lane, glow: clamp01(glow), top, away };
}

// ---------------------------------------------------------------------------
// 帧
// ---------------------------------------------------------------------------

export type HeroFileStage = 'idle' | 'upload' | 'parse' | 'chunk' | 'index' | 'ready';

export const heroAnswerLength =
  heroAnswerIntro.length + heroAnswerItems.reduce((sum, item) => sum + item.lead.length + item.text.length, 0);

export function getHeroFrame(rawTime: number) {
  const t = ((rawTime % HERO_DURATION) + HERO_DURATION) % HERO_DURATION;
  const segmentIndex = Math.max(
    0,
    heroSegments.findIndex((s) => t >= s.start && t < s.end),
  );
  const seg = heroSegments[segmentIndex];

  // --- 拖拽文件 ---
  const dragP = ease(progress(t, 0.5, 2.2));
  const { x: fileX, y: fileY } = dragPoint(dragP);
  const releaseP = ease(progress(t, 2.2, 2.6));
  const dragging = between(t, 0.5, 2.2);
  const file = {
    visible: t < 2.6,
    x: fileX,
    y: fileY,
    lifted: between(t, 0.3, 2.2),
    scale: (between(t, 0.3, 2.2) ? 1.05 : 1) * (1 - 0.65 * releaseP),
    opacity: 1 - releaseP,
    rotate: dragging ? -3 * Math.sin(Math.PI * Math.min(1, dragP * 1.6)) : 0,
  };
  const trail = between(t, 0.55, 2.9) ? { p: dragP, opacity: 1 - progress(t, 2.2, 2.9) } : null;

  // --- 镜头 ---
  const camKey = interp(cameraKeys, t);
  let camera = { x: camKey.x, y: camKey.y, z: camKey.z };
  if (dragging) {
    camera = { x: fileX + 50 * (1 - dragP), y: fileY + 20, z: lerp(1.75, 1.4, dragP) };
  }
  const typeP = progress(t, 9.0, 10.3);
  const caretX = CARET_X0 + QUESTION_W * typeP;
  if (between(t, 8.9, 10.3)) {
    camera = { x: clamp(caretX - 60, 430, CARET_X0 + QUESTION_W - 60), y: INPUT.y + INPUT.h / 2, z: 2 };
  }

  // --- 光标 ---
  const curKey = interp(cursorKeys, t);
  let cursorPos = { x: curKey.x, y: curKey.y };
  if (dragging) cursorPos = { x: fileX + 40, y: fileY + 10 };
  const cursor = {
    x: cursorPos.x,
    y: cursorPos.y,
    visible: !between(t, 9.0, 10.15),
    pressed: between(t, 0.3, 2.2) || between(t, 8.85, 8.98) || between(t, 10.55, 10.7),
  };

  // --- 上传 / 解析 / 分块 / 索引 ---
  const stage: HeroFileStage =
    t < 2.2 ? 'idle' : t < 3.5 ? 'upload' : t < 5 ? 'parse' : t < 7.45 ? 'chunk' : t < 7.9 ? 'index' : 'ready';
  let landed = 0;
  const chunks: Array<{ k: number; x: number; y: number; p: number }> = [];
  for (let k = 0; k < NEW_DOTS; k++) {
    const start = CHUNK_START + k * CHUNK_STAGGER;
    const p = progress(t, start, start + CHUNK_FLIGHT);
    if (p >= 1) landed++;
    else if (p > 0) {
      const from = { x: DOC.x + 40 + ((k * 53) % 120), y: DOC.y + 76 + (k % 8) * 20 };
      const to = dotCenter(EXISTING_DOTS + k);
      const ctrl = { x: (from.x + to.x) / 2, y: Math.min(from.y, to.y) - 110 };
      chunks.push({ k, p, ...quad(from, ctrl, to, ease(p)) });
    }
  }
  const newChunks = Math.round((heroNewFile.chunks * landed) / NEW_DOTS);
  const mdChip = progress(t, 7.75, 8.05);
  const fileCount = heroExistingFiles.length + (t >= 7.75 ? 1 : 0);

  const emergeP = ease(progress(t, 3.5, 4.1));
  const collapseP = ease(progress(t, 7.45, 7.9));
  const docCenter = { x: DOC.x + DOC.w / 2, y: DOC.y + DOC.h / 2 };
  const mdChipCenter = kbChipCenter(3);
  const scanning = between(t, 4.1, 5.0);
  const scanY = 56 + progress(t, 4.1, 5.0) * (DOC.h - 72);
  const doc = {
    visible: between(t, 3.5, 7.9),
    x: collapseP > 0 ? lerp(docCenter.x, mdChipCenter.x, collapseP) : lerp(DROP.x, docCenter.x, emergeP),
    y: collapseP > 0 ? lerp(docCenter.y, mdChipCenter.y, collapseP) : lerp(DROP.y, docCenter.y, emergeP),
    scale: lerp(0.25, 1, emergeP) * lerp(1, 0.12, collapseP),
    opacity: emergeP * (1 - collapseP),
    scanY: scanning ? scanY : null,
    /** 扫描线已经扫过的高度；此线以上的版面元素显示结构标签。 */
    revealY: t < 4.1 ? 0 : scanning ? scanY : DOC.h,
    cutLines: Math.floor((landed / NEW_DOTS) * heroDocLines.length),
  };
  const indexSweep = between(t, 7.45, 7.95) ? progress(t, 7.45, 7.95) : null;
  const indexChips = [between(t, 7.6, 11.2), between(t, 7.8, 11.2)];

  // --- 提问 ---
  const inputAppear = ease(progress(t, 8.2, 8.55));
  const inputCollapse = ease(progress(t, 10.8, 11.2));
  const questionSent = t >= 10.8;
  const input = {
    visible: between(t, 8.2, 11.2),
    opacity: inputAppear * (1 - inputCollapse),
    dy: (1 - inputAppear) * 12,
    scaleX: 1 - 0.5 * inputCollapse,
    focused: between(t, 8.9, 10.8),
    typed: questionSent ? '' : heroQuestion.slice(0, Math.round(heroQuestion.length * typeP)),
    sendPressed: between(t, 10.55, 10.7),
  };
  const pulseP = ease(progress(t, 10.9, 11.4));
  const pulse = {
    visible: between(t, 10.9, 11.5),
    x: DROP.x,
    y: lerp(INPUT.y + INPUT.h / 2, DROP.y, pulseP),
    p: pulseP,
  };
  const query = between(t, 11.35, 14.3) ? { opacity: progress(t, 11.35, 11.6) * (1 - progress(t, 14.0, 14.3)) } : null;

  // --- 检索 ---
  const lanes = heroLanes.map((lane, l) => {
    const elapsed = t - lane.start;
    const hits = LANE_HITS[l].filter((i) => t >= lane.start + distToDrop(i) / RING_SPEED).length;
    return {
      ...lane,
      ring: elapsed >= 0 && elapsed < RING_LIFE ? { r: elapsed * RING_SPEED, opacity: 1 - elapsed / RING_LIFE } : null,
      count: hits,
      chip: between(t, lane.start, 14.3)
        ? progress(t, lane.start, lane.start + 0.2) * (1 - progress(t, 14.0, 14.3))
        : 0,
    };
  });

  // --- 重排 ---
  const sortP = ease(progress(t, 15.1, 15.9));
  const rerank = {
    visible: between(t, 14.0, 17.0),
    opacity: progress(t, 14.0, 14.3) * (1 - progress(t, 16.6, 17.0)),
    sorting: t >= 15.1,
    settled: t >= 15.9,
    rows: heroCandidates.map((cand, i) => {
      const land = candFlightStart(i) + 0.6;
      return {
        ...cand,
        index: i,
        pos: lerp(i, cand.rank, sortP),
        appear: progress(t, land - 0.1, land + 0.15),
        value: lerp(cand.fused, cand.score, sortP),
        top: cand.rank < 5,
        dim: cand.rank < 5 ? 0 : progress(t, 15.9, 16.2),
      };
    }),
  };
  const candFlight = heroCandidates.map((cand, i) => {
    const start = candFlightStart(i);
    const p = ease(progress(t, start, start + 0.6));
    const from = dotCenter(cand.dot);
    const to = { x: RERANK.x + 22, y: rerankRowY(i) };
    const ctrl = { x: (from.x + to.x) / 2, y: Math.min(from.y, to.y) - 90 };
    return { key: `c${cand.dot}`, visible: p > 0 && p < 1, ...quad(from, ctrl, to, p) };
  });
  const top5Flight = TOP5.map((dot, j) => {
    const p = ease(progress(t, 16.6 + j * 0.04, 17.1 + j * 0.04));
    const from = { x: RERANK.x + 22, y: rerankRowY(j) };
    const to = { x: ANSWER.x + ANSWER.w - 72 + j * 11, y: ANSWER.y + 22 };
    const ctrl = { x: (from.x + to.x) / 2, y: Math.min(from.y, to.y) - 60 };
    return { key: `t${dot}`, visible: p > 0 && p < 1, ...quad(from, ctrl, to, p) };
  });

  // --- 回答 ---
  const answerChars = Math.round(heroAnswerLength * progress(t, 17.3, 22.5));
  let consumed = heroAnswerIntro.length;
  const visibleCitations: number[] = [];
  for (const item of heroAnswerItems) {
    consumed += item.lead.length + item.text.length;
    if (answerChars >= consumed) visibleCitations.push(item.cite);
  }
  const answerAppear = ease(progress(t, 16.8, 17.2));
  const answer = {
    visible: t >= 16.8,
    opacity: answerAppear,
    dy: (1 - answerAppear) * 16,
    top5Landed: t >= 17.15,
    chars: answerChars,
    streaming: between(t, 17.3, 22.5),
    done: t >= 22.5,
  };
  const hoveredCitation = between(t, 23.5, 27.4) ? 3 : null;

  // --- 溯源 ---
  const excerpt = {
    visible: t >= 23.6,
    opacity: ease(progress(t, 23.6, 24.0)),
    link: progress(t, 23.6, 24.1),
    mark: progress(t, 24.0, 24.7),
    kbLink: progress(t, 24.3, 24.8),
  };

  // --- 收尾 ---
  const closing = between(t, CLOSING_AT, HERO_DURATION)
    ? {
        p: progress(t, CLOSING_AT, CLOSING_AT + 0.8),
        features: heroFeatures.map((_, i) => progress(t, 26.6 + i * 0.12, 26.9 + i * 0.12)),
      }
    : null;

  let status: string | null = null;
  if (stage === 'upload') status = `上传 ${heroNewFile.name} · ${Math.round(progress(t, 2.3, 3.4) * 100)}%`;
  else if (stage === 'parse') status = '识别标题层级、表格与正文';
  else if (stage === 'chunk') status = `切分段落 ${newChunks} / ${heroNewFile.chunks}`;
  else if (stage === 'index') status = '写入向量与关键词索引';
  else if (between(t, 7.9, 10.9)) status = `${heroNewFile.name} 已就绪 · +${heroNewFile.chunks} 块`;
  else if (between(t, 11.3, 13.9)) status = '三路检索中…';
  else if (between(t, 13.9, 15.9)) status = `重排 ${HERO_CANDIDATES} 段候选…`;
  else if (between(t, 15.9, 17.3)) status = '已选出 5 段依据';

  const ripples = [progress(t, 2.2, 3.0), progress(t, 2.4, 3.3)].filter((p) => p > 0 && p < 1);

  return {
    time: t,
    segment: seg.id,
    segmentIndex,
    segmentProgress: progress(t, seg.start, seg.end),
    closing,
    camera,
    cursor,
    file,
    trail,
    dropHover: between(t, 1.6, 2.5),
    ripples,
    stage,
    status,
    doc,
    indexSweep,
    indexChips,
    chunks,
    newChunks,
    totalChunks: HERO_BASE_CHUNKS + newChunks,
    fileCount,
    mdChip,
    caretX,
    input,
    questionSent,
    pulse,
    query,
    lanes,
    rerank,
    candFlight,
    top5Flight,
    answer,
    visibleCitations,
    hoveredCitation,
    excerpt,
    contentOpacity: t < 0.35 ? progress(t, 0, 0.35) : t >= 27.4 ? 1 - progress(t, 27.4, 27.9) : 1,
  };
}

export type HeroFrame = ReturnType<typeof getHeroFrame>;
