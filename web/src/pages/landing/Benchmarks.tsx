import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';

import { Reveal, SectionHead } from './shared';

/**
 * 设计稿 L1「Benchmarks」：四域中文公开集的多路召回结果 + SciFact 文本重排。
 * 数值为设计稿给出的离线评测结论（四域 2026-07-04，重排 2026-09-29），更新评测后在此同步。
 */
const STATS = [
  { value: '97.25%', unit: 'Recall@10', note: '三路召回 · 四域 394 题实测' },
  { value: '98.73%', unit: 'Hit Rate@10', note: 'Top 10 内找到相关文档的查询占比' },
  { value: '92.43%', unit: 'nDCG@10', note: '排序质量 · 相关文档排得更靠前' },
];

type BarItem = { label: string; value: number; strong: boolean };

const RECALL_BARS: BarItem[] = [
  { label: 'Recall@10', value: 0.9725, strong: true },
  { label: 'Hit Rate@10', value: 0.9873, strong: true },
  { label: 'nDCG@10', value: 0.9243, strong: true },
  { label: 'MRR', value: 0.9216, strong: true },
];

const RECALL_SECONDARY: [string, string, string?][] = [
  ['Recall@5', '0.9170'],
  ['评测查询', '394 题'],
  ['检索 chunk', '3,200'],
];

const RERANK_BARS: BarItem[] = [
  { label: '三路加权（产品默认）', value: 0.8652, strong: false },
  { label: '三路加权 + 文本重排', value: 0.902, strong: true },
];

const RERANK_SECONDARY: [string, string, string?][] = [
  ['nDCG@10', '0.7889', '0.7380'],
  ['MRR@10', '0.7572', '0.7037'],
  ['Hit@5', '0.8633', '0.8133'],
];

const chart = 'flex flex-col rounded-[20px] border border-divider bg-white p-6 shadow-[0_8px_28px_0_rgba(28,26,20,0.05)] md:p-8 lg:h-[454px]';

export function Benchmarks() {
  return (
    <section id="benchmarks" aria-labelledby="bench-title" className="scroll-mt-16 border-t border-divider bg-white px-5 py-20 md:px-[100px] md:py-[120px]">
      <Reveal className="mx-auto flex max-w-[1240px] flex-col items-center">
        <SectionHead
          id="bench-title"
          eyebrow="评测结果"
          title="在公开数据集上验证检索质量"
          width={640}
          desc="在四域中文公开检索集（通用 / 电商 / 视频 / 医疗，394 题、3,200 chunk）上评测，按文档计分，数据与脚本均可复现。"
        />
        <div className="mt-14 grid w-full gap-5 md:grid-cols-3">
          {STATS.map((s) => (
            <div key={s.value} className="flex flex-col gap-1.5 rounded-[20px] border border-divider bg-[#fbfbf9] p-7">
              <p className="flex flex-wrap items-baseline gap-2">
                <span className="font-num text-[clamp(38px,4.2vw,48px)] leading-tight font-semibold tracking-[-0.02em] text-ink">{s.value}</span>
                <span className="text-[13px] font-medium text-text2">{s.unit}</span>
              </p>
              <p className="text-[13px] text-muted">{s.note}</p>
            </div>
          ))}
        </div>

        <div className="mt-6 grid w-full gap-6 lg:grid-cols-2">
          <ChartCard
            title="多路召回：四域中文公开集"
            meta="稠密 + 稀疏 + BM25 加权融合 · 394 题 · 3,200 chunk · 2026-07-04"
            axis="K = 10"
            bars={RECALL_BARS}
            secondary={RECALL_SECONDARY}
          />
          <ChartCard
            title="文本重排：前 30 chunk 离线重排"
            meta="BEIR SciFact 英文公开集 · 300 题 · 前 30 chunk 接 qwen3.7-text-rerank · 离线实验"
            axis="Recall@10"
            bars={RERANK_BARS}
            secondary={RERANK_SECONDARY}
          />
        </div>

        <div className="mt-7 flex w-full flex-col items-start gap-4 md:flex-row md:items-center">
          <p className="flex-1 text-[12px] leading-5 text-muted">数据集：四域中文公开检索集（DuReader / 电商 / 视频 / cMedQA）与 BEIR SciFact；重排为离线实验，尚未接入产品。检索效果会因文档类型和配置而异。</p>
          <Link to="/research" className="flex shrink-0 items-center gap-1.5 rounded-full border border-line px-3.5 py-2 text-[13px] transition-colors hover:border-dash hover:bg-[#fbfbf9]">
            <span className="font-medium text-ink">评测方法与复现</span>
            <span aria-hidden className="font-num text-muted">
              →
            </span>
          </Link>
        </div>
      </Reveal>
    </section>
  );
}

function ChartCard({ title, meta, axis, bars, secondary }: { title: string; meta: string; axis: string; bars: BarItem[]; secondary: [string, string, string?][] }) {
  return (
    <div className={chart}>
      <h3 className="text-[17px] font-medium text-ink">{title}</h3>
      <p className="mt-1.5 text-[12.5px] leading-5 text-muted">{meta}</p>
      <p className="mt-7 font-num text-[12px] font-medium text-text2">{axis}</p>
      <div className="mt-3 flex flex-col gap-3.5">
        {bars.map((b) => (
          <div key={b.label} className="flex flex-col gap-1.5">
            <span className={cn('text-[12.5px]', b.strong ? 'font-medium text-ink' : 'text-text2')}>{b.label}</span>
            <span className="flex items-center gap-2.5">
              <span role="img" aria-label={`${b.label} ${b.value.toFixed(4)}`} className="h-[18px] w-full max-w-[400px] overflow-hidden rounded-[4px] bg-soft">
                <span style={{ width: `${b.value * 100}%` }} className={cn('block h-full rounded-[4px]', b.strong ? 'bg-[#b87a3a]' : 'bg-[#c9c8c0]')} />
              </span>
              <span className={cn('font-num text-[13px] text-ink', b.strong && 'font-semibold')}>{b.value.toFixed(4)}</span>
            </span>
          </div>
        ))}
      </div>
      <div aria-hidden className="mt-3.5 flex w-full max-w-[400px] justify-between font-num text-[10.5px] text-muted">
        <span>0</span>
        <span>0.5</span>
        <span>1.0</span>
      </div>
      <div className="min-h-5 flex-1" />
      <dl className="flex flex-wrap gap-x-6 gap-y-2 border-t border-divider pt-4 font-num">
        {secondary.map(([k, v, from]) => (
          <div key={k} className="flex items-center gap-2">
            <dt className="text-[12px] text-muted">{k}</dt>
            <dd className="text-[12.5px] text-text2">
              {from && <>{from} → </>}
              <span className="font-semibold text-ink">{v}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
