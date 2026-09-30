import { useEffect, useRef, useState } from 'react';

import logo from '@/assets/brand/logo-mark.png';
import { cn } from '@/lib/cn';
import { useReducedMotion } from '@/lib/useReducedMotion';

import { SectionHead, TypeTag, useInView } from './shared';

/**
 * 设计稿 L1「Demo Tabs」+ L2「Tab 演示面板 · 4 态」：
 * 点击 Tab 或每 7 秒自动切换；画布 crossfade，下方进度条填充；悬停暂停；进入视口 30% 才开始播放。
 */
const TABS = [
  {
    id: 'parse',
    label: '解析与分块',
    title: ['统一为 Markdown，', '再切成语义片段'],
    desc: '保留标题层级与原文上下文，表格、代码、公式和图片不被粗暴切断。',
    points: [
      ['标题路径', 'H1 › H2 › H3 写入每个片段'],
      ['整块保留', '表格、代码块不跨片段'],
      ['上下文重叠', '相邻片段共享 64 tokens'],
    ],
  },
  {
    id: 'index',
    label: '三路索引',
    title: ['稠密、稀疏与 BM25', '三路并行构建'],
    desc: '以 MySQL 为真值源，向量与关键词索引均可诊断、可重建，任何一路出问题都能单独修复。',
    points: [
      ['稠密向量', '捕获语义相似'],
      ['稀疏向量', '保留术语权重'],
      ['BM25', '精确关键词匹配'],
    ],
  },
  {
    id: 'retrieve',
    label: '混合检索',
    title: ['三路并行召回，', '加权融合排序'],
    desc: '同时覆盖语义相似、术语表达与精确关键词，优先保留真正相关的片段，过滤看似相关的噪声。',
    points: [
      ['并行召回', '三路同时检索，互不阻塞'],
      ['RRF 融合', '按排名加权合并'],
      ['阈值过滤', '低于 0.5 不进入上下文'],
    ],
  },
  {
    id: 'answer',
    label: '有据回答',
    title: ['回填原文，', '有据地流式回答'],
    desc: '按上下文预算回填命中片段，流式生成并保留引用；没有依据时明确不回答。',
    points: [
      ['引用溯源', '悬停即看原文段落'],
      ['上下文预算', '自动裁剪，不超出窗口'],
      ['无据拒答', '0 命中时直接说明'],
    ],
  },
] as const;

const AUTOPLAY_MS = 7000;

export function DemoTabs() {
  const [active, setActive] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [hover, setHover] = useState(false);
  const reduced = useReducedMotion();
  const [ref, inView] = useInView<HTMLDivElement>(0.3);
  const running = inView && !hover && !reduced;
  const last = useRef(0);

  useEffect(() => {
    if (!running) return;
    last.current = performance.now();
    const t = window.setInterval(() => {
      const now = performance.now();
      const dt = now - last.current;
      last.current = now;
      if (document.hidden) return;
      setElapsed((e) => {
        if (e + dt < AUTOPLAY_MS) return e + dt;
        setActive((a) => (a + 1) % TABS.length);
        return 0;
      });
    }, 100);
    return () => window.clearInterval(t);
  }, [running]);

  const select = (i: number) => {
    setActive(i);
    setElapsed(0);
  };
  const tab = TABS[active];

  return (
    <section id="demo" aria-labelledby="demo-title" className="flex scroll-mt-20 flex-col items-center px-6 pt-10 pb-[120px]">
      <SectionHead id="demo-title" eyebrow="工作原理" title="从上传到有据回答，一条链路完成" desc="点击任一步骤，看看 LinkRag 在后台实际做了什么。" />
      <div role="tablist" aria-label="工作原理步骤" className="mt-10 flex max-w-full gap-0.5 overflow-x-auto rounded-full bg-[#efeee9] p-1">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={i === active}
            aria-controls="demo-panel"
            onClick={() => select(i)}
            className={cn('flex shrink-0 items-center gap-2 rounded-full px-[18px] py-[9px] transition-colors', i === active ? 'bg-white shadow-[0_1px_3px_0_rgba(28,26,20,0.08)]' : 'hover:bg-white/50')}
          >
            <span className={cn('font-num text-[11px] font-medium', i === active ? 'text-[#a8733f]' : 'text-muted')}>0{i + 1}</span>
            <span className={cn('text-[14px]', i === active ? 'font-medium text-ink' : 'text-text2')}>{t.label}</span>
          </button>
        ))}
      </div>
      <div
        ref={ref}
        id="demo-panel"
        role="tabpanel"
        aria-labelledby={`tab-${tab.id}`}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        className="mt-7 w-full max-w-[1240px] overflow-hidden rounded-[20px] bg-soft lg:h-[560px] lg:rounded-[24px]"
      >
        {/* 桌面（≥1024）：左侧文案 + 右侧 840×560 画布 */}
        <div className="hidden h-full lg:flex">
          <div className="flex w-[400px] shrink-0 flex-col pt-14 pr-10 pb-12 pl-14">
            <p className="text-[12.5px] font-medium text-[#a8733f]">
              0{active + 1} · {tab.label}
            </p>
            <h3 key={tab.id} className="mt-4 animate-tab-in font-serif text-[30px] leading-[42px] font-semibold text-ink">
              {tab.title[0]}
              <br />
              {tab.title[1]}
            </h3>
            <p className="mt-4 w-[300px] text-[14.5px] leading-[25px] text-text2">{tab.desc}</p>
            <div className="flex-1" />
            <dl className="flex flex-col">
              {tab.points.map(([k, v]) => (
                <div key={k} className="flex items-center gap-3 border-t border-line py-[11px]">
                  <dt className="text-[13px] font-medium text-ink">{k}</dt>
                  <span className="flex-1" />
                  <dd className="text-[12.5px] text-muted">{v}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-6 flex items-center gap-2.5">
              <span className="h-[3px] w-40 overflow-hidden rounded-[2px] bg-ink/8">
                <span className="block h-full rounded-[2px] bg-brand" style={{ width: `${reduced ? 100 : (elapsed / AUTOPLAY_MS) * 100}%` }} />
              </span>
              <span className="text-[11px] text-muted">{reduced ? '手动切换' : hover ? '已暂停' : '自动播放 · 7s'}</span>
            </div>
          </div>
          <div className="relative flex-1 overflow-hidden">
            {/* key 变化触发 crossfade 与内部元素重新入场 */}
            <div key={tab.id} className="absolute inset-0 animate-tab-in">
              {active === 0 && <ParseCanvas />}
              {active === 1 && <IndexCanvas />}
              {active === 2 && <RetrieveCanvas />}
              {active === 3 && <AnswerCanvas />}
            </div>
          </div>
        </div>

        {/* 窄屏（设计稿 L4）：画布按宽度等比缩放，下接标题、说明与分页点 */}
        <div className="flex flex-col gap-3 p-4 lg:hidden">
          <ScaledCanvas key={tab.id}>
            {active === 0 && <ParseCanvas />}
            {active === 1 && <IndexCanvas />}
            {active === 2 && <RetrieveCanvas />}
            {active === 3 && <AnswerCanvas />}
          </ScaledCanvas>
          <h3 className="font-serif text-[18px] font-semibold text-ink">
            {tab.title[0]}
            {tab.title[1]}
          </h3>
          <p className="text-[13.5px] leading-[22px] text-text2">{tab.desc}</p>
          <span className="flex gap-1.5" aria-hidden>
            {TABS.map((t, i) => (
              <span key={t.id} className={cn('h-1.5 rounded-[3px] transition-[width,background-color]', i === active ? 'w-[18px] bg-brand' : 'w-1.5 bg-ink/15')} />
            ))}
          </span>
        </div>
      </div>
    </section>
  );
}

/* ---------------- 画布（840×560，按设计稿坐标绝对定位） ---------------- */

const CANVAS_W = 840;
const CANVAS_H = 560;

/** 窄屏：把 840×560 画布按容器宽度等比缩小，保持设计稿中的相对位置 */
function ScaledCanvas({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.4);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setScale(el.clientWidth / CANVAS_W);
    update();
    if (typeof ResizeObserver === 'undefined') return;
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return (
    <div ref={ref} style={{ height: CANVAS_H * scale }} className="relative w-full animate-tab-in overflow-hidden rounded-[14px] bg-white shadow-[0_6px_18px_0_rgba(28,26,20,0.06)]">
      <div aria-hidden style={{ width: CANVAS_W, height: CANVAS_H, transform: `scale(${scale})` }} className="absolute top-0 left-0 origin-top-left">
        {children}
      </div>
    </div>
  );
}

const card = 'absolute rounded-[14px] border border-divider bg-white';
const shadow = 'shadow-[0_6px_20px_0_rgba(28,26,20,0.06)]';
const stagger = (i: number, step = 180) => ({ animationDelay: `${i * step}ms` });

const CHUNKS = [
  { n: 1, path: '产品规划 › 核心场景', tok: 412, text: '围绕用户核心场景，提供可验证的解决方案…', bar: '#7d9a7e' },
  { n: 2, path: '核心场景 › 性能目标', tok: 286, text: '| 指标 | 一期 | 二期 |　表格整块保留', bar: '#c8925a', hi: true },
  { n: 3, path: '产品规划 › 迭代节奏', tok: 398, text: '性能目标放到二期迭代，一期先保证可用…', bar: '#7b8fa8' },
];

function ParseCanvas() {
  return (
    <>
      <div className={cn(card, shadow, 'top-[118px] left-10 flex w-[250px] flex-col gap-[9px] p-[18px]')}>
        <div className="flex items-center gap-2">
          <TypeTag type="PDF" />
          <span className="text-[12.5px] font-medium text-ink">产品规划.pdf</span>
        </div>
        <span className="h-[7px] w-[170px] rounded-[2px] bg-ink/70" />
        {[214, 196, 150].map((w) => (
          <span key={w} style={{ width: w }} className="h-[5px] rounded-[2px] bg-ink/14" />
        ))}
        <span className="relative h-12 w-[214px] rounded-[4px] bg-soft">
          <span className="absolute inset-x-0 top-4 h-px bg-line" />
          <span className="absolute inset-x-0 top-8 h-px bg-line" />
          <span className="absolute inset-y-0 left-[71px] w-px bg-line" />
          <span className="absolute inset-y-0 left-[142px] w-px bg-line" />
        </span>
        {[206, 180, 120].map((w) => (
          <span key={w} style={{ width: w }} className="h-[5px] rounded-[2px] bg-ink/14" />
        ))}
      </div>
      {/* 扫描线：在文档卡片范围内上下扫描 */}
      <span aria-hidden style={{ ['--scan' as string]: '200px' }} className="absolute top-[130px] left-[30px] h-[2px] w-[270px] animate-scan rounded-[1px] bg-[#c8925a] shadow-[0_0_10px_0_rgba(200,146,90,0.5)]" />
      <svg aria-hidden className="absolute top-[279px] left-[304px]" width="60" height="2">
        <line x1="0" y1="1" x2="60" y2="1" stroke="#c8925a" strokeWidth="1.5" strokeDasharray="4 3" />
      </svg>
      <div className={cn(card, shadow, 'top-[86px] left-[372px] flex w-[450px] flex-col gap-2 p-4')}>
        <div className="flex items-center gap-2">
          <TypeTag type="MD" />
          <span className="text-[12.5px] font-medium text-ink">产品规划.md</span>
          <span className="flex-1" />
          <span className="text-[11px] text-muted">128 个片段</span>
        </div>
        {CHUNKS.map((c, i) => (
          <div key={c.n} style={stagger(i + 1)} className={cn('flex animate-stagger-up overflow-hidden rounded-[10px] border', c.hi ? 'border-[#c8925a]/50 bg-[#f6f1e9]' : 'border-divider bg-[#fbfbf9]')}>
            <span style={{ background: c.bar }} className="w-[3px] shrink-0" />
            <div className="flex min-w-0 flex-1 flex-col gap-1 px-3 py-2.5">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-ink">片段 {c.n}</span>
                <span className="text-[10.5px] text-muted">{c.path}</span>
                <span className="flex-1" />
                <span className="font-mono text-[10px] text-muted">{c.tok} tok</span>
              </div>
              <span className="truncate text-[12px] text-text2">{c.text}</span>
            </div>
          </div>
        ))}
        <div style={stagger(4)} className="flex animate-stagger-up rounded-[10px] border border-dashed border-divider bg-[#fbfbf9] px-3 py-2.5">
          <span className="h-1.5 w-[180px] animate-pulse rounded-[3px] bg-ink/8" />
        </div>
      </div>
    </>
  );
}

const VECTOR = [10, 18, 24, 14, 20, 12, 22, 16, 25, 11, 19, 15, 23, 13, 17, 21, 12, 18, 24, 14, 20, 16, 10, 22];

function IndexHead({ color, name, meta, state }: { color: string; name: string; meta: string; state: string }) {
  return (
    <div className="flex items-center gap-2">
      <span style={{ background: color }} className="size-2 rounded-full" />
      <span className="text-[12.5px] font-medium text-ink">{name}</span>
      <span className="text-[11px] text-muted">{meta}</span>
      <span className="flex-1" />
      <span className={cn('text-[10.5px]', state === '写入中' ? 'text-[#a8733f]' : 'text-muted')}>{state}</span>
    </div>
  );
}

function IndexCanvas() {
  return (
    <>
      <div className={cn(card, shadow, 'top-[212px] left-9 flex w-[220px] flex-col gap-2 p-[15px]')}>
        <span className="text-[11.5px] font-medium text-ink">片段 12</span>
        <span className="text-[12px] leading-[19px] text-text2">文档变更时只对受影响的分块进行增量重建。</span>
        <span className="text-[11px] text-muted">技术说明.docx · p.1</span>
      </div>
      <svg aria-hidden className="absolute top-0 left-0" width="840" height="560" fill="none">
        {[
          ['M256 268 C 308 268, 308 88, 360 88', '#7b8fa8'],
          ['M256 268 C 308 268, 308 237, 360 237', '#7d9a7e'],
          ['M256 268 C 308 268, 308 388, 360 388', '#c8925a'],
        ].map(([d, c], i) => (
          <path key={c} d={d} stroke={c} strokeWidth="1.5" style={{ ['--len' as string]: 260, animationDelay: `${i * 150}ms` }} className="animate-draw" />
        ))}
      </svg>
      <div style={stagger(1, 150)} className={cn(card, 'top-12 left-[360px] flex w-[420px] animate-stagger-up flex-col gap-2.5 p-[15px]')}>
        <IndexHead color="#7b8fa8" name="稠密向量" meta="Qdrant · 1024 维" state="已写入" />
        <div className="flex h-[25px] items-end gap-[3px]">
          {VECTOR.map((h, i) => (
            <span key={i} style={{ height: h, opacity: 0.3 + h / 45 }} className="w-[13px] rounded-[2px] bg-[#7b8fa8]" />
          ))}
        </div>
      </div>
      <div style={stagger(2, 150)} className={cn(card, 'top-[198px] left-[360px] flex w-[420px] animate-stagger-up flex-col gap-2.5 p-[15px]')}>
        <IndexHead color="#7d9a7e" name="稀疏向量" meta="SPLADE · 词项权重" state="已写入" />
        <div className="flex gap-1.5">
          {[
            ['增量', 0.82],
            ['重建', 0.74],
            ['分块', 0.61],
            ['索引', 0.43],
            ['文档', 0.28],
          ].map(([t, w]) => (
            <span key={t} style={{ background: `rgba(125,154,126,${0.1 + (w as number) * 0.17})` }} className="flex items-center gap-1.5 rounded-[6px] px-2 py-1">
              <span className="text-[11.5px] text-ink">{t}</span>
              <span className="font-mono text-[10px] text-text2">{(w as number).toFixed(2)}</span>
            </span>
          ))}
        </div>
      </div>
      <div style={stagger(3, 150)} className={cn(card, 'top-[348px] left-[360px] flex w-[420px] animate-stagger-up flex-col gap-2.5 p-[15px]')}>
        <IndexHead color="#c8925a" name="BM25" meta="Manticore · 倒排索引" state="写入中" />
        <div className="flex gap-1.5">
          {[
            ['增量', 'd12 d48 d97'],
            ['重建', 'd12 d33'],
            ['分块', 'd3 d12 …'],
          ].map(([t, d]) => (
            <span key={t} className="flex items-center gap-1.5 rounded-[6px] border border-line px-2 py-[5px]">
              <span className="text-[11.5px] font-medium text-ink">{t}</span>
              <span className="font-mono text-[10px] text-muted">{d}</span>
            </span>
          ))}
        </div>
      </div>
      <span className="absolute top-[470px] left-9 flex items-center gap-2 rounded-full border border-line bg-white py-[9px] pr-3.5 pl-[13px] text-[11.5px] text-text2">
        <span aria-hidden className="size-1.5 rounded-full bg-ink" />
        MySQL 真值源 · 任一索引可一键重建
      </span>
    </>
  );
}

const LANES = [
  { name: '稠密', color: '#7b8fa8', rows: [['注意力分配权重', 0.94], ['长距离依赖', 0.87], ['多头子空间', 0.79], ['学习率震荡', 0.31]] },
  { name: '稀疏', color: '#7d9a7e', rows: [['长距离依赖', 0.84], ['注意力分配权重', 0.91], ['多头子空间', 0.76], ['学习率震荡', 0.28]] },
  { name: 'BM25', color: '#c8925a', rows: [['注意力分配权重', 0.88], ['多头子空间', 0.73], ['学习率震荡', 0.25], ['长距离依赖', 0.81]] },
] as const;

function RetrieveCanvas() {
  return (
    <>
      <span className="absolute top-10 left-[280px] flex items-center gap-2 rounded-full border border-line bg-white py-[11px] pr-4 pl-[13px]">
        <span aria-hidden className="text-[14px] text-muted">⌕</span>
        <span className="text-[13.5px] text-ink">为什么需要注意力机制？</span>
      </span>
      {LANES.map((l, i) => (
        <div key={l.name} style={{ left: 28 + i * 262 }} className={cn(card, 'top-[108px] flex w-[236px] animate-stagger-up flex-col gap-1.5 p-[13px]')}>
          <div className="mb-0.5 flex items-center gap-1.5">
            <span style={{ background: l.color }} className="size-[7px] rounded-full" />
            <span className="text-[12px] font-medium text-ink">{l.name}</span>
            <span className="flex-1" />
            <span className="font-num text-[10.5px] text-muted">Top-4</span>
          </div>
          {l.rows.map(([t, s], j) => {
            const low = s < 0.5;
            return (
              <div key={t} className={cn('flex h-[26px] items-center gap-1.5 rounded-lg px-2', !low && 'bg-[#fbfbf9]')}>
                <span className="w-2 font-num text-[10.5px] font-medium text-muted">{j + 1}</span>
                <span className={cn('text-[11.5px]', low ? 'text-muted' : 'text-ink')}>{t}</span>
                <span className="flex-1" />
                <span className="font-mono text-[10px] text-muted">{s.toFixed(2)}</span>
              </div>
            );
          })}
        </div>
      ))}
      <svg aria-hidden className="absolute top-0 left-0" width="840" height="560" fill="none">
        {['M146 281 C 146 310, 420 300, 420 329', 'M408 281 L 420 329', 'M670 281 C 670 310, 420 300, 420 329'].map((d, i) => (
          <path key={d} d={d} stroke="#e4e4e0" strokeWidth="1.5" strokeDasharray="4 4" style={{ animationDelay: `${300 + i * 100}ms` }} className="animate-stagger-up" />
        ))}
      </svg>
      <div style={{ animationDelay: '800ms' }} className="absolute top-[333px] left-[210px] flex w-[420px] animate-stagger-up flex-col gap-2 rounded-[14px] border border-[#c8925a] bg-[#f6f1e9] p-[15px]">
        <div className="flex items-center">
          <span className="text-[12.5px] font-medium text-ink">融合结果</span>
          <span className="flex-1" />
          <span className="font-mono text-[10.5px] text-[#a8733f]">RRF · k=60</span>
        </div>
        {[
          ['注意力分配权重', 0.94],
          ['长距离依赖', 0.87],
          ['多头子空间', 0.79],
        ].map(([t, s], i) => (
          <div key={t} className="flex items-center gap-2.5">
            <span className="w-2 font-num text-[11px] font-semibold text-[#a8733f]">{i + 1}</span>
            <span className="text-[12px] text-ink">{t}</span>
            <span className="flex-1" />
            <span className="h-1 w-20 overflow-hidden rounded-[2px] bg-ink/6">
              <span style={{ width: `${(s as number) * 80}px` }} className="block h-full rounded-[2px] bg-[#c8925a]" />
            </span>
            <span className="w-[26px] text-right font-mono text-[10.5px] text-text2">{(s as number).toFixed(2)}</span>
          </div>
        ))}
      </div>
    </>
  );
}

const ANSWER_TEXT = '注意力机制会为不同 token 分配权重，突出与当前语义最相关的信息 [1]。自注意力可以直接建模长距离依赖 [2]，多头结构则让模型在多个子空间并行学习 [3]。';

/** 逐 token 流出：每个字 20–35ms 随机抖动（减少动效时直接展示全文） */
function useStreamed(text: string) {
  const reduced = useReducedMotion();
  const [n, setN] = useState(reduced ? text.length : 0);
  useEffect(() => {
    if (reduced) return setN(text.length);
    let i = 0;
    let t: number;
    const tick = () => {
      i += 1;
      setN(i);
      if (i < text.length) t = window.setTimeout(tick, 20 + Math.random() * 15);
    };
    t = window.setTimeout(tick, 300);
    return () => window.clearTimeout(t);
  }, [text, reduced]);
  return text.slice(0, n);
}

function AnswerCanvas() {
  const shown = useStreamed(ANSWER_TEXT);
  const done = shown.length === ANSWER_TEXT.length;
  const cited = (n: number) => shown.includes(`[${n}]`);
  const cites = [
    { n: 1, name: 'Transformer 笔记.pdf' },
    { n: 2, name: '深度学习讲义.md' },
    { n: 3, name: '论文精读.docx' },
  ];
  return (
    <>
      <div className={cn(card, 'top-[60px] left-9 flex w-[500px] flex-col gap-3 p-[21px]')}>
        <div className="flex items-center gap-2">
          <img src={logo} alt="" className="size-5 object-contain" />
          <span className="font-num text-[12.5px] font-semibold text-ink">LinkRag</span>
          <span className="flex-1" />
          <span className="text-[11px] text-muted">基于 3 个来源</span>
        </div>
        <p className="min-h-[75px] text-[14px] leading-[25px] text-ink">
          {shown.split(/(\[\d\])/).map((part, i) =>
            /^\[\d\]$/.test(part) ? (
              <span key={i} className="font-num font-semibold text-[#a8733f]">
                {part}
              </span>
            ) : (
              part
            ),
          )}
          {!done && <span aria-hidden className="ml-0.5 inline-block h-[15px] w-[2px] animate-caret-amber rounded-[1px] bg-[#c8925a] align-[-2px]" />}
        </p>
        <div className="flex gap-1.5">
          {cites.map((c) => (
            <span
              key={c.n}
              className={cn(
                'flex items-center gap-1.5 rounded-lg border py-[5px] pr-2.5 pl-[7px] transition-[opacity,background-color,border-color] duration-300',
                cited(c.n) ? 'opacity-100' : 'opacity-30',
                c.n === 2 && cited(2) ? 'border-[#c8925a] bg-[#f6f1e9]' : 'border-divider bg-[#fbfbf9]',
              )}
            >
              <span className={cn('rounded-[4px] px-[5px] font-num text-[9.5px] font-semibold', c.n === 2 && cited(2) ? 'bg-[#c8925a] text-white' : 'bg-soft text-text2')}>{c.n}</span>
              <span className="text-[10.5px] text-text2">{c.name}</span>
            </span>
          ))}
        </div>
      </div>
      {cited(2) && (
        <>
          <svg aria-hidden className="absolute top-[246px] left-24 animate-hero-window" width="14" height="21" viewBox="0 0 14 21">
            <path d="M1 1 L1 17 L5 13 L8 20 L10.5 19 L7.5 12 L13 12 Z" fill="#1d1d1b" stroke="#fff" strokeWidth="1.2" strokeLinejoin="round" />
          </svg>
          <div className="absolute top-[266px] left-[110px] flex w-[300px] animate-stagger-up flex-col gap-2 rounded-[14px] border border-[#c8925a] bg-white p-[15px] shadow-pop">
            <div className="flex items-center gap-1.5">
              <TypeTag type="MD" />
              <span className="text-[11.5px] font-medium text-ink">深度学习讲义.md</span>
              <span className="text-[10.5px] text-muted">§4.2</span>
            </div>
            <p className="text-[12px] leading-5 text-text2">与 RNN 逐步传递不同，自注意力可以直接建模长距离依赖，减少序列位置带来的信息衰减。</p>
            <span className="text-[11px] text-[#a8733f]">打开原文 →</span>
          </div>
        </>
      )}
      <div className={cn(card, 'top-[60px] left-[580px] flex w-[260px] flex-col gap-2 p-[15px]')}>
        <div className="flex items-center">
          <span className="text-[12px] font-medium text-ink">上下文预算</span>
          <span className="flex-1" />
          <span className="font-mono text-[10.5px] text-muted">3.2k / 8k</span>
        </div>
        <span className="flex h-2 w-[232px] overflow-hidden rounded-[3px] bg-soft">
          <span className="w-10 bg-ink/50" />
          <span className="w-[140px] bg-[#c8925a]/80" />
          <span className="w-3 bg-[#7b8fa8]/70" />
        </span>
        <span className="flex gap-3">
          {[
            ['系统', 'bg-ink/80'],
            ['片段', 'bg-[#c8925a]/80'],
            ['问题', 'bg-[#7b8fa8]/80'],
          ].map(([l, c]) => (
            <span key={l} className="flex items-center gap-[5px] text-[10.5px] text-muted">
              <span className={cn('size-1.5 rounded-full', c)} />
              {l}
            </span>
          ))}
        </span>
      </div>
      <div className={cn(card, 'top-[157px] left-[580px] flex w-[260px] flex-col gap-2 p-[15px]')}>
        <span className="text-[11.5px] text-muted">Q：明年股价会涨吗？</span>
        <span className="text-[12.5px] leading-5 text-ink">知识库中没有相关依据，我不会编造答案。</span>
        <span className="self-start rounded-full bg-[#c86a5a]/10 px-2 py-0.5 text-[10.5px] text-[#c86a5a]">0 条命中 · 已拒答</span>
      </div>
    </>
  );
}
