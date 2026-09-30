import { useEffect, useRef, useState } from 'react';
import { ArrowUp, Check, FileText, Loader2, MousePointer2, Pause, Play, Sparkles } from 'lucide-react';

import logo from '@/assets/brand/logo-mark.png';
import { cn } from '@/lib/cn';
import { useReducedMotion } from '@/lib/useReducedMotion';

import {
  ANSWER,
  CITE3_DOT,
  DOC,
  DROP,
  EXCERPT,
  GRID,
  HERO_CANDIDATES,
  HERO_DURATION,
  HERO_STATIC_TIME,
  INPUT,
  KB,
  KB_CHIP,
  RERANK,
  RERANK_H,
  SOURCE_ROW_X,
  SOURCE_ROW_Y,
  TOTAL_DOTS,
  WIDE_CAMERA,
  WORLD_H,
  WORLD_W,
  dotCenter,
  dotState,
  dragPoint,
  getHeroFrame,
  heroAnswerIntro,
  heroAnswerItems,
  heroClosing,
  heroDocLines,
  heroExcerpt,
  heroExistingFiles,
  heroFeatures,
  heroLanes,
  heroNewFile,
  heroQuestion,
  heroSegments,
  heroSources,
  type HeroFrame,
} from './heroTimeline';

const ACCENT = '#c8925a';

const typeTone: Record<string, string> = {
  PDF: 'bg-[#f6e4df] text-[#a4553f]',
  DOCX: 'bg-[#e2e9f5] text-[#46618e]',
  XLSX: 'bg-[#dff0e3] text-[#3f7a52]',
  MD: 'bg-[#f5eadc] text-[#9a6532]',
};

const palettes = {
  light: {
    ink: 'text-[#1d1d1b]',
    body: 'text-[#55554f]',
    mute: 'text-[#96968f]',
    line: 'border-[#e8e5df]',
    card: 'bg-white/90',
    solid: 'bg-white',
    chip: 'bg-[#f5f3ef]',
    dot: '#dcd7cd',
    fresh: '#e6c29a',
    slot: '#e0dbd1',
    stage: 'from-[#fbf8f3] via-[#f7f1e8] to-[#f3ece1]',
    grid: 'rgba(120,100,70,0.08)',
    vignette: 'rgba(120,90,50,0.10)',
  },
  dark: {
    ink: 'text-[#ededea]',
    body: 'text-[#b8b7b1]',
    mute: 'text-[#85847e]',
    line: 'border-[#393731]',
    card: 'bg-[#1f1e1a]/90',
    solid: 'bg-[#1f1e1a]',
    chip: 'bg-[#2a2924]',
    dot: '#3b3933',
    fresh: '#8a6541',
    slot: '#34322c',
    stage: 'from-[#191815] via-[#1c1a16] to-[#201c17]',
    grid: 'rgba(255,240,220,0.05)',
    vignette: 'rgba(0,0,0,0.35)',
  },
};

type Palette = (typeof palettes)['light'];

const cardShadow = 'shadow-[0_1px_0_rgba(255,255,255,0.7)_inset,0_24px_60px_-24px_rgba(80,50,20,0.28)]';

/** 胶片颗粒：一张极淡的 SVG 噪点纹理。 */
const GRAIN = `url("data:image/svg+xml;utf8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 0.35  0 0 0 0 0.27  0 0 0 0 0.18  0 0 0 0.55 0"/></filter><rect width="160" height="160" filter="url(#n)"/></svg>',
)}")`;

/** 按真实流逝时间推进的演示时钟：持续自动播放，仅手动暂停时停止（离屏 / 标签页隐藏时不计时，回到画面继续）。 */
function useHeroClock(enabled: boolean) {
  const [time, setTime] = useState(0);
  const [userPaused, setUserPaused] = useState(false);
  const [inView, setInView] = useState(true);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const running = enabled && !userPaused && inView;

  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold: 0.15 });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!running) return;
    let last = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      if (!document.hidden) setTime((prev) => (prev + Math.min(dt, 1)) % HERO_DURATION);
    }, 1000 / 30);
    return () => window.clearInterval(timer);
  }, [running]);

  return { time, setTime, rootRef, userPaused, setUserPaused };
}

function useElementSize() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 1160, h: 652 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return { ref, size };
}

/**
 * 落地页 Hero 演示（28s 循环）：设计稿 L1「Hero Backdrop」中的演示窗口 + 下方分段时间轴。
 * 窗口外框（macOS 标题栏 + URL）按设计稿还原，窗口内容为镜头跟随的世界画布动画（剧本见 heroTimeline）。
 */
export default function HeroDemo({ darkMode }: { darkMode?: boolean }) {
  const reducedMotion = useReducedMotion();
  const { time, setTime, rootRef, userPaused, setUserPaused } = useHeroClock(!reducedMotion);
  const f = getHeroFrame(reducedMotion ? HERO_STATIC_TIME : time);
  const c = darkMode ? palettes.dark : palettes.light;
  const { ref: viewportRef, size } = useElementSize();
  const segment = heroSegments[f.segmentIndex];
  const narrow = size.w < 640;

  // 镜头：把 camera 指向的世界坐标放到视口中心。窄屏整体再放大一些，保证文字可读。
  const cam = reducedMotion ? WIDE_CAMERA : f.camera;
  const s = (size.w / WORLD_W) * cam.z * (narrow ? 1.3 : 1);
  const worldTransform = `translate(${size.w / 2 - cam.x * s}px, ${size.h / 2 - cam.y * s}px) scale(${s})`;

  return (
    <div ref={rootRef} className="flex w-full flex-col items-center">
      {/* 演示窗口：macOS 标题栏 + 画布；宽度随视口高度收缩，保证窗口与时间轴同屏 */}
        <div className="relative flex w-full max-w-[min(1160px,calc((100svh-210px)*1.72))] animate-hero-window flex-col overflow-hidden rounded-[20px] border border-divider bg-white shadow-[0_2px_6px_0_rgba(28,26,20,0.05),0_24px_64px_0_rgba(28,26,20,0.12)]">
          <div className="flex items-center border-b border-divider px-4 py-3">
            {/* macOS 窗口按钮：关闭 / 最小化 / 全屏 */}
            <span aria-hidden className="flex items-center gap-2">
              {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
                <span key={c} style={{ background: c }} className="size-3 rounded-full shadow-[inset_0_0_0_0.5px_rgba(0,0,0,0.18)]" />
              ))}
            </span>
          </div>

          <div
            ref={viewportRef}
            role="img"
            aria-label="LinkRag 演示：把文件拖进知识库，识别文档结构后切块写入双索引；提问后三路检索召回候选，重排留下最相关的 5 段，生成带引用的回答，并溯源到刚上传文件的原文"
            className={cn('relative aspect-[4/3] w-full overflow-hidden bg-gradient-to-br sm:aspect-[16/9]', c.stage)}
          >
            {/* 背景点阵随镜头轻微视差移动 */}
            <div
              aria-hidden
              className="absolute inset-[-40px]"
              style={{
                backgroundImage: `radial-gradient(${c.grid} 1px, transparent 1.3px)`,
                backgroundSize: '22px 22px',
                transform: `translate(${-(cam.x - WORLD_W / 2) * 0.04}px, ${-(cam.y - WORLD_H / 2) * 0.04}px)`,
              }}
            />
            <div aria-hidden className={cn('absolute top-[10%] left-[18%] h-[70%] w-[60%] rounded-full blur-[110px]', darkMode ? 'bg-[#5a3e24]/25' : 'bg-[#f1cfa6]/45')} />

            <div
              className="absolute top-0 left-0 origin-top-left will-change-transform"
              style={{ width: WORLD_W, height: WORLD_H, transform: worldTransform, opacity: reducedMotion ? 1 : f.contentOpacity }}
            >
              <KnowledgeBase f={f} c={c} />
              <Constellation f={f} c={c} />
              <DocumentCard f={f} c={c} />
              <RerankPanel f={f} c={c} />
              <FlightLayer f={f} darkMode={darkMode} />
              <QuestionInput f={f} c={c} darkMode={darkMode} />
              <AnswerCard f={f} c={c} darkMode={darkMode} />
              <Excerpt f={f} c={c} darkMode={darkMode} />
              <DraggedFile f={f} c={c} />
              {!reducedMotion && f.cursor.visible && (
                <MousePointer2
                  aria-hidden
                  size={22}
                  strokeWidth={1.6}
                  className="absolute top-0 left-0 fill-[#1d1d1b] text-white drop-shadow-[0_3px_4px_rgba(0,0,0,0.25)]"
                  style={{
                    transform: `translate(${f.cursor.x - 4}px, ${f.cursor.y - 3}px) scale(${f.cursor.pressed ? 0.86 : 1})`,
                    transformOrigin: '4px 3px',
                  }}
                />
              )}
            </div>

            {/* 暗角与胶片颗粒，让画面更有质感 */}
            <div aria-hidden className="pointer-events-none absolute inset-0" style={{ background: `radial-gradient(120% 90% at 50% 45%, transparent 55%, ${c.vignette} 100%)` }} />
            <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.35] mix-blend-multiply" style={{ backgroundImage: GRAIN, backgroundSize: '160px 160px' }} />

            {!f.closing && <StepHud f={f} c={c} darkMode={darkMode} narrow={narrow} />}
            {f.closing && !reducedMotion && <Closing f={f} c={c} darkMode={darkMode} narrow={narrow} />}
          </div>
        </div>

      {/* 读屏：当前步骤说明（视觉上由时间轴高亮表达） */}
      <p className="sr-only" aria-live="polite">
        第 {f.segmentIndex + 1} 步 {segment.title}：{segment.desc}
      </p>

      {/* Demo Timeline：暂停 + 7 段进度，点击跳转；已完成段为墨色，当前段为琥珀色 */}
      {!reducedMotion && (
        <div className="mt-4 flex w-full max-w-[320px] items-center gap-2 sm:mt-6 sm:w-auto sm:max-w-full sm:gap-[18px] sm:rounded-full sm:border sm:border-line sm:bg-white sm:py-2 sm:pr-5 sm:pl-2">
          <button
            type="button"
            onClick={() => setUserPaused((p) => !p)}
            aria-label={userPaused ? '播放演示' : '暂停演示'}
            className="hidden size-[26px] shrink-0 items-center justify-center rounded-full bg-soft text-ink transition-colors hover:bg-active sm:flex"
          >
            {userPaused ? <Play aria-hidden className="size-2.5 fill-current" /> : <Pause aria-hidden className="size-2.5 fill-current" />}
          </button>
          {heroSegments.map((seg, i) => {
            const fill = i < f.segmentIndex ? 1 : i === f.segmentIndex ? f.segmentProgress : 0;
            const active = i === f.segmentIndex;
            return (
              <button
                key={seg.id}
                type="button"
                onClick={() => setTime(seg.start)}
                aria-label={`跳到「${seg.label}」`}
                aria-current={active ? 'step' : undefined}
                className="group flex min-w-0 flex-1 flex-col items-start gap-1.5 sm:flex-none"
              >
                <span className="h-[3px] w-full overflow-hidden rounded-[2px] bg-ink/8 sm:w-[clamp(40px,7vw,96px)]">
                  <span className={cn('block h-full rounded-[2px]', active ? 'bg-[#c8925a]' : 'bg-brand')} style={{ width: `${fill * 100}%` }} />
                </span>
                <span className={cn('text-[10px] transition-colors sm:text-[11.5px]', active ? 'font-medium text-ink' : i < f.segmentIndex ? 'text-ink' : 'text-muted group-hover:text-text2')}>{seg.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * 顶部步骤胶囊：左侧是当前步骤（编号 + 标题），右侧是实时状态。
 * 固定在视口内、不随镜头缩放，换步骤时整体淡入。
 */
function StepHud({ f, c, darkMode, narrow }: { f: HeroFrame; c: Palette; darkMode?: boolean; narrow: boolean }) {
  const seg = heroSegments[f.segmentIndex];
  const done = f.status?.includes('已');
  return (
    <div className="pointer-events-none absolute inset-x-0 top-4 flex justify-center px-4">
      <div
        key={seg.id}
        className={cn(
          'hero-fade-in flex max-w-full items-center gap-2.5 rounded-full border py-1.5 pl-1.5 pr-3.5 backdrop-blur-md',
          'shadow-[0_8px_24px_-12px_rgba(80,50,20,0.25)]',
          c.line,
          darkMode ? 'bg-[#1f1e1a]/80' : 'bg-white/85',
        )}
      >
        <span
          className="flex h-6 min-w-6 items-center justify-center rounded-full px-1.5 font-num text-[10px] font-semibold tabular-nums text-white"
          style={{ background: ACCENT }}
        >
          {String(f.segmentIndex + 1).padStart(2, '0')}
        </span>
        <span className={cn('shrink-0 whitespace-nowrap text-[13px] font-medium', c.ink)}>{seg.title}</span>
        {f.status && !narrow && (
          <>
            <span className={cn('h-3.5 w-px shrink-0', darkMode ? 'bg-[#393731]' : 'bg-[#e4e0d8]')} />
            <span
              // 按阶段而不是文案重挂载：百分比 / 计数变化时原地更新，不重复淡入（否则每帧闪动、几乎透明）
              key={f.stage === 'upload' || f.stage === 'chunk' ? f.stage : f.status}
              className={cn('hero-fade-in flex min-w-0 items-center gap-1.5 text-xs tabular-nums', c.body)}
            >
              {done ? (
                <Check size={12} className="shrink-0 text-[#3f7a52]" />
              ) : (
                <Loader2 size={12} className="shrink-0 animate-spin" style={{ color: ACCENT }} />
              )}
              <span className="truncate">{f.status}</span>
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/** 收尾全景：品牌标语逐字出现，随后三个功能标签依次浮现。 */
function Closing({ f, c, darkMode, narrow }: { f: HeroFrame; c: Palette; darkMode?: boolean; narrow: boolean }) {
  if (!f.closing) return null;
  const plate = darkMode ? 'from-[#191815]/85' : 'from-[#fbf8f3]/90';
  const shown = heroClosing.title.slice(0, Math.round(heroClosing.title.length * f.closing.p));
  return (
    <div className={cn('pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t to-transparent', plate)}>
      <div
        className={cn('flex flex-col items-center gap-3 text-center', narrow ? 'px-4 pb-4 pt-10' : 'px-8 pb-8 pt-16')}
      >
        <div className={cn('font-serif font-semibold tracking-tight', narrow ? 'text-lg' : 'text-[28px]', c.ink)}>
          {shown}
          <span className="invisible">{heroClosing.title.slice(shown.length)}</span>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {heroFeatures.map((feat, i) => {
            const p = f.closing?.features[i] ?? 0;
            return (
              <span
                key={feat}
                className={cn(
                  'rounded-full border px-3 py-1 text-[11px] backdrop-blur-sm',
                  c.line,
                  c.body,
                  darkMode ? 'bg-[#1f1e1a]/70' : 'bg-white/70',
                )}
                style={{ opacity: p, transform: `translateY(${(1 - p) * 6}px)` }}
              >
                {feat}
              </span>
            );
          })}
        </div>
        <div className={cn('text-[11px]', c.mute)} style={{ opacity: f.closing.features[2] }}>
          {heroClosing.desc}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 世界画布里的元素：全部按世界坐标绝对定位，由外层 transform 实现镜头
// ---------------------------------------------------------------------------

function TypeBadge({ type, className }: { type: string; className?: string }) {
  return (
    <span
      className={cn(
        'flex shrink-0 items-center justify-center rounded-md font-num font-semibold tracking-tight',
        typeTone[type],
        className,
      )}
    >
      {type}
    </span>
  );
}

function KnowledgeBase({ f, c }: { f: HeroFrame; c: Palette }) {
  const chips = [...heroExistingFiles, heroNewFile];
  return (
    <div
      className={cn(
        'absolute overflow-hidden rounded-[22px] border backdrop-blur-sm transition-[border-color,box-shadow] duration-200',
        c.card,
        f.dropHover
          ? 'border-[#d9b48c] shadow-[0_0_0_6px_rgba(200,146,90,0.14),0_24px_60px_-24px_rgba(80,50,20,0.3)]'
          : cn(c.line, cardShadow),
      )}
      style={{ left: KB.x, top: KB.y, width: KB.w, height: KB.h }}
    >
      <div className="flex items-start justify-between px-[22px] pt-[18px]">
        <div>
          <div className={cn('font-serif text-[17px] font-semibold', c.ink)}>产品知识库</div>
          <div className={cn('mt-0.5 font-num text-[11px] tabular-nums', c.mute)}>
            {f.fileCount} 个文件 · {f.totalChunks.toLocaleString('en-US')} 个分块
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {f.lanes.map(
            (lane) =>
              lane.chip > 0 && (
                <span
                  key={lane.label}
                  className={cn(
                    'flex items-center gap-1 rounded-full px-2 py-[3px] text-[10px] tabular-nums',
                    c.chip,
                    c.body,
                  )}
                  style={{ opacity: lane.chip }}
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: lane.color }} />
                  {lane.label} {lane.count}
                </span>
              ),
          )}
          {(['向量索引', '关键词索引'] as const).map(
            (label, i) =>
              f.indexChips[i] && (
                <span
                  key={label}
                  className="hero-fade-in flex items-center gap-1 rounded-full bg-[#3f7a52]/10 px-2 py-[3px] text-[10px] text-[#3f7a52]"
                >
                  <Check size={10} strokeWidth={2.4} />
                  {label}
                </span>
              ),
          )}
        </div>
      </div>

      {/* 写入索引时，一道光从左到右扫过星图 */}
      {f.indexSweep !== null && (
        <div
          className="pointer-events-none absolute inset-y-0 w-24"
          style={{
            left: -96 + f.indexSweep * (KB.w + 96),
            background: 'linear-gradient(90deg, transparent, rgba(200,146,90,0.22), transparent)',
          }}
        />
      )}

      <div className="absolute flex gap-2" style={{ left: KB_CHIP.x0 - KB.x, top: KB_CHIP.y - KB.y - 12 }}>
        {chips.map((file, i) => {
          const isNew = i === chips.length - 1;
          if (isNew && f.mdChip <= 0) return null;
          return (
            <span
              key={file.name}
              className={cn(
                'flex h-6 items-center gap-1.5 rounded-lg px-1.5 text-[10px]',
                isNew ? 'bg-[#c8925a]/15 text-[#9a6532]' : cn(c.chip, c.body),
              )}
              style={{
                width: KB_CHIP.w,
                opacity: isNew ? f.mdChip : 1,
                transform: isNew ? `scale(${0.8 + 0.2 * f.mdChip})` : undefined,
              }}
            >
              <TypeBadge type={file.type} className="h-4 w-6 text-[7px]" />
              <span className="truncate">{file.name}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

/** 分块星图 + 涟漪 + 拖拽轨迹 + 检索波纹 / 连线 + 溯源连线，统一画在一张世界坐标 SVG 上。 */
function Constellation({ f, c }: { f: HeroFrame; c: Palette }) {
  const half = GRID.dot / 2;
  const cite = dotCenter(CITE3_DOT);
  const row3 = { x: SOURCE_ROW_X, y: SOURCE_ROW_Y[2] };
  const excerptRight = { x: EXCERPT.x + EXCERPT.w, y: EXCERPT.y + 34 };
  const excerptTop = { x: EXCERPT.x + 120, y: EXCERPT.y };
  const dots = Array.from({ length: TOTAL_DOTS }, (_, i) => ({ i, d: dotState(i, f.time), ...dotCenter(i) }));

  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute left-0 top-0 overflow-visible"
      width={WORLD_W}
      height={WORLD_H}
    >
      {/* 拖拽轨迹：沿抛物线的一串小点 */}
      {f.trail &&
        Array.from({ length: 14 }, (_, k) => {
          const q = (k / 14) * f.trail!.p;
          if (f.trail!.p - q > 0.55) return null;
          const pt = dragPoint(q);
          return (
            <circle
              key={k}
              cx={pt.x}
              cy={pt.y}
              r={1.8}
              fill={ACCENT}
              opacity={f.trail!.opacity * (1 - (f.trail!.p - q) / 0.55) * 0.7}
            />
          );
        })}

      {f.ripples.map((p, i) => (
        <circle
          key={i}
          cx={DROP.x}
          cy={DROP.y}
          r={20 + p * 170}
          fill="none"
          stroke={ACCENT}
          strokeWidth={1.5}
          opacity={(1 - p) * 0.55}
        />
      ))}

      {f.lanes.map(
        (lane) =>
          lane.ring && (
            <circle
              key={lane.label}
              cx={DROP.x}
              cy={DROP.y}
              r={lane.ring.r}
              fill="none"
              stroke={lane.color}
              strokeWidth={2}
              opacity={lane.ring.opacity * 0.7}
            />
          ),
      )}

      {/* 查询节点到命中分块的连线 */}
      {f.query &&
        dots.map(
          ({ i, d, x, y }) =>
            d.glow > 0 &&
            d.lane >= 0 &&
            !d.away && (
              <line
                key={`q${i}`}
                x1={DROP.x}
                y1={DROP.y}
                x2={x}
                y2={y}
                stroke={heroLanes[d.lane].color}
                strokeWidth={0.8}
                opacity={d.glow * f.query!.opacity * 0.45}
              />
            ),
        )}

      {dots.map(({ i, d, x, y }) => {
        if (!d.present) {
          return (
            <rect
              key={i}
              x={x - half + 1}
              y={y - half + 1}
              width={GRID.dot - 2}
              height={GRID.dot - 2}
              rx={2}
              fill="none"
              stroke={c.slot}
              strokeDasharray="2 2"
            />
          );
        }
        const lit = d.glow > 0 && d.lane >= 0;
        const color = lit ? heroLanes[d.lane].color : d.fresh ? c.fresh : c.dot;
        // 静止时分块轻微闪烁，像呼吸一样
        const twinkle = 0.82 + 0.18 * Math.sin(f.time * 1.6 + i * 2.39);
        return (
          <g key={i} opacity={d.away ? 0.3 : 1}>
            {d.glow > 0 && (
              <rect
                x={x - half - 4}
                y={y - half - 4}
                width={GRID.dot + 8}
                height={GRID.dot + 8}
                rx={5}
                fill={color}
                opacity={d.glow * 0.22}
              />
            )}
            <rect
              x={x - half}
              y={y - half}
              width={GRID.dot}
              height={GRID.dot}
              rx={2.5}
              fill={color}
              opacity={lit ? 0.55 + 0.45 * d.glow : twinkle}
            />
          </g>
        );
      })}

      {/* 查询节点 */}
      {f.query && (
        <g opacity={f.query.opacity}>
          <circle cx={DROP.x} cy={DROP.y} r={14} fill={ACCENT} opacity={0.16} />
          <circle cx={DROP.x} cy={DROP.y} r={6} fill={ACCENT} />
          <circle cx={DROP.x} cy={DROP.y} r={6} fill="none" stroke="#fff" strokeWidth={1.5} />
        </g>
      )}

      {/* 溯源：来源行 → 原文摘录 → 星图中的原文分块 */}
      {f.excerpt.link > 0 && (
        <path
          d={`M ${row3.x} ${row3.y} C ${row3.x - 60} ${row3.y}, ${excerptRight.x + 60} ${excerptRight.y}, ${excerptRight.x} ${excerptRight.y}`}
          fill="none"
          stroke={ACCENT}
          strokeWidth={1.6}
          pathLength={1}
          strokeDasharray={`${f.excerpt.link} 1`}
        />
      )}
      {f.excerpt.kbLink > 0 && (
        <>
          <path
            d={`M ${excerptTop.x} ${excerptTop.y} C ${excerptTop.x} ${excerptTop.y - 50}, ${cite.x} ${cite.y + 60}, ${cite.x} ${cite.y + 8}`}
            fill="none"
            stroke={ACCENT}
            strokeWidth={1.4}
            pathLength={1}
            strokeDasharray={`${f.excerpt.kbLink} 1`}
            opacity={0.8}
          />
          <circle
            cx={cite.x}
            cy={cite.y}
            r={10 + 6 * f.excerpt.kbLink}
            fill="none"
            stroke={ACCENT}
            strokeWidth={1.4}
            opacity={f.excerpt.kbLink}
          />
        </>
      )}
    </svg>
  );
}

function DocumentCard({ f, c }: { f: HeroFrame; c: Palette }) {
  if (!f.doc.visible) return null;
  return (
    <div
      className={cn('absolute overflow-hidden rounded-2xl border', c.solid, c.line, cardShadow)}
      style={{
        left: f.doc.x - DOC.w / 2,
        top: f.doc.y - DOC.h / 2,
        width: DOC.w,
        height: DOC.h,
        transform: `scale(${f.doc.scale})`,
        opacity: f.doc.opacity,
      }}
    >
      <div className="flex items-center gap-2 px-4 pt-4">
        <TypeBadge type={heroNewFile.type} className="h-7 w-7 text-[9px]" />
        <div className="min-w-0">
          <div className={cn('truncate text-xs font-medium', c.ink)}>{heroNewFile.name}</div>
          <div className={cn('text-[10px]', c.mute)}>{heroNewFile.size}</div>
        </div>
      </div>

      {heroDocLines.map((ln, i) => {
        const revealed = f.doc.revealY >= ln.y + ln.h / 2;
        const cut = i < f.doc.cutLines;
        const isHeading = ln.kind === 'h1' || ln.kind === 'h2';
        const baseFill = isHeading ? 'rgba(29,29,27,0.26)' : 'rgba(29,29,27,0.1)';
        return (
          <div key={i} className="absolute left-4 right-4" style={{ top: ln.y }}>
            {ln.kind === 'table' ? (
              <div
                className={cn(
                  'grid grid-cols-3 gap-[3px] rounded-md border p-[3px] transition-colors duration-200',
                  revealed ? 'border-[#7d8fb0]/60' : c.line,
                )}
                style={{ height: ln.h, opacity: cut ? 0.35 : 1 }}
              >
                {Array.from({ length: 6 }, (_, k) => (
                  <span
                    key={k}
                    className="rounded-[2px]"
                    style={{ background: k < 3 ? 'rgba(29,29,27,0.14)' : 'rgba(29,29,27,0.07)' }}
                  />
                ))}
              </div>
            ) : (
              <div
                className="rounded-full transition-[background-color,opacity] duration-200"
                style={{
                  width: `${ln.w * 100}%`,
                  height: ln.h,
                  background: cut ? ACCENT : revealed && isHeading ? '#1d1d1b' : baseFill,
                  opacity: cut ? 0.28 : revealed && isHeading ? 0.55 : 1,
                }}
              />
            )}
            {ln.tag && revealed && !cut && (
              <span
                className={cn(
                  'hero-fade-in absolute -top-[3px] right-0 rounded px-1 font-num text-[8px] font-semibold leading-[13px]',
                  ln.kind === 'table' ? 'bg-[#7d8fb0]/15 text-[#4f6184]' : 'bg-[#c8925a]/15 text-[#9a6532]',
                )}
              >
                {ln.tag}
              </span>
            )}
            {cut && <div className="absolute -left-1 -right-1 top-[-5px] border-t border-dashed border-[#c8925a]/60" />}
          </div>
        );
      })}

      {f.doc.scanY !== null && (
        <>
          <div
            className="absolute inset-x-0"
            style={{
              top: 50,
              height: f.doc.scanY - 50,
              background: 'linear-gradient(180deg, transparent, rgba(200,146,90,0.08))',
            }}
          />
          <div
            className="absolute inset-x-0 h-[2px]"
            style={{ top: f.doc.scanY, background: ACCENT, boxShadow: `0 0 12px ${ACCENT}` }}
          />
        </>
      )}
    </div>
  );
}

/** 重排面板：候选按融合分进入，重排后按新分数平滑换位，前 5 名高亮。 */
function RerankPanel({ f, c }: { f: HeroFrame; c: Palette }) {
  if (!f.rerank.visible) return null;
  return (
    <div
      className={cn('absolute overflow-hidden rounded-[22px] border backdrop-blur-sm', c.card, c.line, cardShadow)}
      style={{ left: RERANK.x, top: RERANK.y, width: RERANK.w, height: RERANK_H, opacity: f.rerank.opacity }}
    >
      <div className={cn('flex h-[56px] items-center gap-2 border-b px-4', c.line)}>
        <span className={cn('font-serif text-[15px] font-semibold', c.ink)}>重排</span>
        <span className={cn('text-[11px] tabular-nums', c.mute)}>
          {HERO_CANDIDATES} 段候选 · 显示前 {f.rerank.rows.length} 段
        </span>
        <span
          className={cn(
            'ml-auto rounded-full px-2 py-0.5 text-[10px] transition-colors duration-300',
            f.rerank.sorting ? 'bg-[#c8925a]/15 text-[#9a6532]' : cn(c.chip, c.mute),
          )}
        >
          {f.rerank.sorting ? '重排分数' : '融合分数'}
        </span>
      </div>

      {f.rerank.rows.map((row) => (
        <div
          key={row.dot}
          className="absolute left-0 right-0 flex items-center gap-2.5 px-4"
          style={{
            top: RERANK.head + row.pos * RERANK.rowH,
            height: RERANK.rowH,
            opacity: row.appear * (1 - 0.6 * row.dim),
          }}
        >
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
            style={{ background: row.lane >= 0 ? heroLanes[row.lane].color : ACCENT }}
          />
          <span
            className={cn(
              'w-4 shrink-0 text-right font-num text-[10px] tabular-nums',
              f.rerank.settled && row.top ? 'font-semibold text-[#9a6532]' : c.mute,
            )}
          >
            {Math.round(row.pos) + 1}
          </span>
          <TypeBadge type={row.type} className="h-4 w-8 text-[7px]" />
          <span className={cn('min-w-0 flex-1 truncate text-[11px]', c.ink)}>
            {row.file}
            <span className={cn('ml-1.5', c.mute)}>{row.loc}</span>
          </span>
          <span className={cn('h-1 w-16 shrink-0 overflow-hidden rounded-full', c.chip)}>
            <span
              className="block h-full rounded-full"
              style={{ width: `${row.value * 100}%`, background: f.rerank.settled && row.top ? ACCENT : '#c9c4ba' }}
            />
          </span>
          <span className={cn('w-8 shrink-0 text-right font-num text-[10px] tabular-nums', c.body)}>
            {row.value.toFixed(2)}
          </span>
        </div>
      ))}

      {/* 前 5 名的分界线 */}
      <div
        className="absolute left-4 right-4 border-t border-dashed border-[#c8925a]/70 transition-opacity duration-300"
        style={{ top: RERANK.head + 5 * RERANK.rowH, opacity: f.rerank.settled ? 1 : 0 }}
      >
        <span className="absolute -top-2 right-0 rounded-full bg-[#c8925a] px-1.5 text-[9px] font-medium leading-4 text-white">
          Top 5
        </span>
      </div>

      <div
        className={cn(
          'absolute bottom-0 left-0 right-0 flex h-10 items-center border-t px-4 text-[10px]',
          c.line,
          c.mute,
        )}
      >
        <span className="flex items-center gap-3">
          {heroLanes.map((l) => (
            <span key={l.label} className="flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: l.color }} />
              {l.label}
            </span>
          ))}
        </span>
      </div>
    </div>
  );
}

function FlightLayer({ f, darkMode }: { f: HeroFrame; darkMode?: boolean }) {
  const dot = (x: number, y: number, scale = 1) =>
    `translate(${x - GRID.dot / 2}px, ${y - GRID.dot / 2}px) scale(${scale})`;
  const glow = '0 0 14px rgba(200,146,90,0.6)';
  return (
    <>
      {f.chunks.map((chunk) => (
        <span
          key={chunk.k}
          className="absolute left-0 top-0 rounded-[2.5px]"
          style={{
            width: GRID.dot,
            height: GRID.dot,
            background: ACCENT,
            transform: dot(chunk.x, chunk.y, 1.4 - 0.4 * chunk.p),
            boxShadow: glow,
          }}
        />
      ))}
      {[...f.candFlight, ...f.top5Flight].map(
        (fl) =>
          fl.visible && (
            <span
              key={fl.key}
              className="absolute left-0 top-0 rounded-[2.5px]"
              style={{
                width: GRID.dot,
                height: GRID.dot,
                background: ACCENT,
                transform: dot(fl.x, fl.y),
                boxShadow: glow,
              }}
            />
          ),
      )}
      {f.pulse.visible && (
        <span
          className="absolute left-0 top-0 h-3 w-3 rounded-full"
          style={{
            background: darkMode ? '#f3d2ae' : ACCENT,
            transform: `translate(${f.pulse.x - 6}px, ${f.pulse.y - 6}px) scale(${1 + 0.6 * Math.sin(Math.PI * f.pulse.p)})`,
            boxShadow: '0 0 0 6px rgba(200,146,90,0.18), 0 0 24px rgba(200,146,90,0.7)',
          }}
        />
      )}
    </>
  );
}

function DraggedFile({ f, c }: { f: HeroFrame; c: Palette }) {
  if (!f.file.visible) return null;
  return (
    <div
      className={cn(
        'absolute flex w-[200px] items-center gap-3 rounded-2xl border px-3.5 py-3',
        c.solid,
        c.line,
        f.file.lifted
          ? 'shadow-[0_28px_50px_-16px_rgba(60,40,20,0.35),0_8px_16px_-8px_rgba(60,40,20,0.2)]'
          : 'shadow-[0_10px_24px_-12px_rgba(60,40,20,0.25)]',
      )}
      style={{
        left: f.file.x - 100,
        top: f.file.y - 32,
        transform: `rotate(${f.file.rotate}deg) scale(${f.file.scale})`,
        opacity: f.file.opacity,
      }}
    >
      <TypeBadge type={heroNewFile.type} className="h-9 w-9 text-[10px]" />
      <div className="min-w-0">
        <div className={cn('truncate text-[13px] font-medium', c.ink)}>{heroNewFile.name}</div>
        <div className={cn('text-[11px]', c.mute)}>{heroNewFile.size} · 发布流程与回滚预案</div>
      </div>
    </div>
  );
}

function QuestionInput({ f, c, darkMode }: { f: HeroFrame; c: Palette; darkMode?: boolean }) {
  if (!f.input.visible) return null;
  const typing = f.input.focused && f.input.typed.length < heroQuestion.length;
  return (
    <div
      className={cn(
        'absolute flex items-center gap-3 rounded-[18px] border pl-5 pr-2.5 transition-[border-color,box-shadow] duration-200',
        c.solid,
        f.input.focused
          ? 'border-[#d9b48c] shadow-[0_0_0_5px_rgba(200,146,90,0.13),0_18px_40px_-20px_rgba(80,50,20,0.3)]'
          : cn(c.line, cardShadow),
      )}
      style={{
        left: INPUT.x,
        top: INPUT.y,
        width: INPUT.w,
        height: INPUT.h,
        opacity: f.input.opacity,
        transform: `translateY(${f.input.dy}px) scaleX(${f.input.scaleX})`,
      }}
    >
      <Sparkles size={16} style={{ color: ACCENT }} className="shrink-0" />
      <span className={cn('min-w-0 flex-1 whitespace-nowrap text-[15px]', f.input.typed ? c.ink : c.mute)}>
        {f.input.typed || '向产品知识库提问…'}
        {typing && (
          <span
            className="ml-0.5 inline-block h-[17px] w-[2px] translate-y-[3px] rounded-full"
            style={{ background: ACCENT }}
          />
        )}
      </span>
      <span
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white transition-[background-color,transform] duration-150',
          f.input.typed ? (darkMode ? 'bg-[#c8925a]' : 'bg-brand') : darkMode ? 'bg-[#3a3934]' : 'bg-[#d6d4ce]',
          f.input.sendPressed && 'scale-90',
        )}
      >
        <ArrowUp size={16} strokeWidth={2.2} />
      </span>
    </div>
  );
}

function AnswerCard({ f, c, darkMode }: { f: HeroFrame; c: Palette; darkMode?: boolean }) {
  if (!f.answer.visible) return null;

  // 回答按字符流出：先引言，再三条要点（加粗的要点名 + 说明），每条结尾带引用
  let remaining = f.answer.chars;
  const take = (s: string) => {
    const shown = s.slice(0, Math.max(0, remaining));
    remaining -= s.length;
    return shown;
  };
  const intro = take(heroAnswerIntro);
  const items = heroAnswerItems.map((item) => ({ ...item, leadShown: take(item.lead), textShown: take(item.text) }));

  return (
    <div
      className={cn('absolute rounded-[22px] border backdrop-blur-sm', c.card, c.line, cardShadow)}
      style={{
        left: ANSWER.x,
        top: ANSWER.y,
        width: ANSWER.w,
        height: ANSWER.h,
        opacity: f.answer.opacity,
        transform: `translateY(${f.answer.dy}px)`,
      }}
    >
      <div className={cn('flex items-center gap-2 border-b px-4 py-3', c.line)}>
        <img src={logo} alt="" className="h-5 w-5 object-contain" />
        <span className={cn('text-[13px] font-semibold', c.ink)}>LinkRag</span>
        <span className={cn('ml-auto flex items-center gap-1.5 text-[10px]', c.mute)}>
          基于 5 段依据
          <span className="flex gap-[3px]">
            {[0, 1, 2, 3, 4].map((i) => (
              <span
                key={i}
                className="h-2 w-2 rounded-[2px] transition-colors duration-200"
                style={{ background: f.answer.top5Landed ? ACCENT : darkMode ? '#3b3933' : '#e4dfd5' }}
              />
            ))}
          </span>
        </span>
      </div>

      <div className="px-4 pt-3">
        <div className={cn('rounded-xl px-3 py-2 text-[12px] leading-5', c.chip, c.body)}>{heroQuestion}</div>
        <div className={cn('mt-3 text-[13px] leading-[1.85]', c.body)}>
          <p className={c.ink}>{intro}</p>
          <ol className="mt-1 flex flex-col gap-0.5">
            {items.map(
              (item, i) =>
                item.leadShown && (
                  <li key={item.cite} className="flex gap-2">
                    <span className={cn('font-num text-xs leading-[1.85] tabular-nums', c.mute)}>{i + 1}.</span>
                    <span>
                      <strong className={cn('font-semibold', c.ink)}>{item.leadShown}</strong>
                      {item.textShown}
                      {f.visibleCitations.includes(item.cite) && (
                        <Citation n={item.cite} active={f.hoveredCitation === item.cite} />
                      )}
                    </span>
                  </li>
                ),
            )}
          </ol>
          {f.answer.streaming && (
            <span
              className="ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 animate-pulse rounded-full"
              style={{ background: ACCENT }}
            />
          )}
        </div>
      </div>

      {/* 来源行，位置与 SOURCE_ROW_Y 对齐，溯源连线从第 3 行出发 */}
      {heroSources.map((src, i) => {
        if (!f.visibleCitations.includes(src.id)) return null;
        const hovered = f.hoveredCitation === src.id;
        return (
          <div
            key={src.id}
            className={cn(
              'hero-fade-in absolute flex h-6 items-center gap-2 rounded-lg px-2 text-[11px] transition-[background-color,box-shadow] duration-200',
              hovered && 'bg-[#c8925a]/12 shadow-[0_0_0_1px_rgba(200,146,90,0.5)]',
            )}
            style={{ left: SOURCE_ROW_X - ANSWER.x, right: 16, top: SOURCE_ROW_Y[i] - ANSWER.y - 12 }}
          >
            <span
              className={cn(
                'flex h-4 min-w-4 items-center justify-center rounded font-num text-[9px] font-semibold',
                hovered ? 'bg-[#c8925a] text-white' : 'bg-[#c8925a]/15 text-[#9a6532]',
              )}
            >
              {src.id}
            </span>
            <TypeBadge type={src.type} className="h-4 w-7 text-[7px]" />
            <span className={cn('min-w-0 flex-1 truncate', c.ink)}>{src.file}</span>
            {src.fresh && <span className="rounded-full bg-[#c8925a]/15 px-1.5 text-[9px] text-[#9a6532]">刚上传</span>}
            <span className={cn('font-num tabular-nums', c.mute)}>
              {src.loc} · {src.score}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Citation({ n, active }: { n: number; active: boolean }) {
  return (
    <span
      className={cn(
        'hero-fade-in mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-md px-1 align-middle font-num text-[10px] font-semibold transition-colors duration-150',
        active ? 'bg-[#c8925a] text-white' : 'bg-[#c8925a]/15 text-[#9a6532]',
      )}
    >
      {n}
    </span>
  );
}

function Excerpt({ f, c, darkMode }: { f: HeroFrame; c: Palette; darkMode?: boolean }) {
  if (!f.excerpt.visible) return null;
  const markBg = darkMode ? 'rgba(200,146,90,0.4)' : '#f3dcbf';
  return (
    <div
      className={cn('absolute rounded-[18px] border border-[#e3c7a6] p-4', c.solid, cardShadow)}
      style={{
        left: EXCERPT.x,
        top: EXCERPT.y,
        width: EXCERPT.w,
        minHeight: EXCERPT.h,
        opacity: f.excerpt.opacity,
        transform: `translateY(${(1 - f.excerpt.opacity) * 10}px)`,
      }}
    >
      <div className="flex items-center gap-2">
        <TypeBadge type={heroNewFile.type} className="h-6 w-6 text-[8px]" />
        <span className={cn('text-[13px] font-medium', c.ink)}>{heroNewFile.name}</span>
        <span className={cn('font-num text-[11px]', c.mute)}>§2.3 发布与回滚</span>
        <span className="ml-auto rounded-full bg-[#c8925a]/15 px-2 py-0.5 text-[10px] text-[#9a6532]">
          刚上传 · 已被引用
        </span>
      </div>
      <p className={cn('mt-3 text-[14px] leading-[1.8]', c.body)}>
        <FileText size={12} className={cn('mr-1 inline -translate-y-px', c.mute)} />
        {heroExcerpt.before}
        <span
          className={cn('rounded-[3px] px-0.5 py-px', c.ink)}
          style={{
            backgroundImage: `linear-gradient(${markBg}, ${markBg})`,
            backgroundRepeat: 'no-repeat',
            backgroundSize: `${f.excerpt.mark * 100}% 100%`,
          }}
        >
          {heroExcerpt.mark}
        </span>
      </p>
    </div>
  );
}
