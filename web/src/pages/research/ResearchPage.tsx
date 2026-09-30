import { X } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/cn';
import { GITHUB_URL, PageIntro, pill } from '@/pages/landing/shared';
import { PublicShell, SCROLL_ROOT_ID } from '@/pages/landing/SiteChrome';

import { Bar, btn, Dropdown, ext, Metric, RawDownload, SectionHead, useCopy, useScrollSpy } from './components';
import {
  ADVANTAGES,
  CODE_TABS,
  COMPARE_ISSUE_URL,
  COMPARE_STAGES,
  META,
  OVERVIEW,
  PLANNED,
  R10_CONFIGS,
  ALL_RAW_RESULTS_URL,
  RELEASES_URL,
  REPORT_TYPES,
  REPORTS,
  reproCommand,
  REPRO_FACTS,
  ROUNDS,
  VERSIONS,
  WHY,
  type Report,
  type ReportType,
} from './data';

/**
 * 设计稿「06 落地页」L6 研究与评测 · 桌面（交互见 L9）。
 * 落地页「评测方法与复现」跳转到此页。
 */
const SECTIONS = [
  { id: 'overview', label: '概览' },
  { id: 'compare', label: '开源项目对比' },
  { id: 'ablation', label: '消融实验' },
  { id: 'reports', label: '历史报告' },
  { id: 'repro', label: '复现指南' },
];

const wrap = 'mx-auto w-full max-w-[1240px]';
const section = 'scroll-mt-[128px] border-t border-divider px-5 py-14 md:px-[100px] md:py-[72px]';

export default function ResearchPage() {
  const [version, setVersion] = useState('all');
  const [asking, setAsking] = useState(false);
  return (
    <PublicShell>
      <Header />
      <SubNav version={version} onVersion={setVersion} />
      <Overview />
      <Compare onAsk={() => setAsking(true)} />
      <Ablation />
      <Reports version={version} />
      <Repro />
      {asking && <CompareRequestDialog onClose={() => setAsking(false)} />}
    </PublicShell>
  );
}

function Header() {
  return (
    <PageIntro
      title="研究与评测"
      desc="LinkRag 在公开数据集上的全部评测：开源项目同口径对比、逐轮消融、历史报告。每个数字都能追溯到一次运行和一份原始结果。"
      aside={
      <div className="flex flex-wrap gap-2">
        <RawDownload href={ALL_RAW_RESULTS_URL} disabledTitle="全部原始结果暂未公开" className={cn(pill.secondary, btn.md)}>
          下载原始结果
          <span aria-hidden className="font-num text-[13px] text-muted">
            ↓
          </span>
        </RawDownload>
        <a href={GITHUB_URL} {...ext} className={cn(pill.secondary, btn.md)}>
          复现仓库
          <span aria-hidden className="font-num text-[13px] text-muted">
            ↗
          </span>
        </a>
      </div>
      }
    >
      <dl className="mt-9 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-divider pt-5 sm:grid-cols-3 lg:flex lg:gap-0">
        {META.map((m, i) => (
          <div key={m.label} className={cn('flex min-w-0 flex-col gap-1', i > 0 && 'lg:ml-7 lg:border-l lg:border-divider lg:pl-7')}>
            <dt className="text-[12px] text-muted">{m.label}</dt>
            <dd className="text-[13.5px] font-medium text-ink">{m.value}</dd>
          </div>
        ))}
      </dl>
    </PageIntro>
  );
}

function SubNav({ version, onVersion }: { version: string; onVersion: (v: string) => void }) {
  const active = useScrollSpy(
    SECTIONS.map((s) => s.id),
    SCROLL_ROOT_ID,
  );
  return (
    <div className="sticky top-16 z-20 bg-[#fbfbf9]/90 px-5 backdrop-blur-md md:top-[73px] md:px-[100px]">
      <div className={cn(wrap, 'flex items-center gap-6 border-b border-divider')}>
        <nav aria-label="页内导航" className="flex min-w-0 flex-1 gap-7 overflow-x-auto overflow-y-hidden [scrollbar-width:none]">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              aria-current={active === s.id ? 'true' : undefined}
              className={cn('-mb-px shrink-0 border-b-2 pt-3.5 pb-3.5 text-[14.5px] whitespace-nowrap transition-colors', active === s.id ? 'border-brand font-medium text-ink' : 'border-transparent text-text2 hover:text-ink')}
            >
              {s.label}
            </a>
          ))}
        </nav>
        <Dropdown
          variant="plain"
          label="评测版本"
          value={version}
          onChange={onVersion}
          options={[{ value: 'all', label: '全部版本', desc: `共 ${REPORTS.length} 份报告` }, ...VERSIONS.map((v) => ({ value: v.id, label: v.id, desc: v.desc }))]}
          footer={
            <a href={RELEASES_URL} {...ext} className="text-[#a8733f] hover:underline">
              查看版本变更记录
            </a>
          }
        />
      </div>
    </div>
  );
}

function Overview() {
  return (
    <section id="overview" aria-labelledby="overview-title" className="scroll-mt-[128px] px-5 pt-12 pb-6 md:px-[100px] md:pt-14">
      <div className={cn(wrap, 'flex flex-col gap-5')}>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <h2 id="overview-title" className="font-serif text-[28px] font-semibold text-ink">
            概览
          </h2>
          <span className="flex-1" />
          <p className="text-[13px] text-muted">BEIR SciFact · 5,183 篇文档 · 官方 test 300 题 · 源文档级</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {OVERVIEW.map((o) => (
            <div key={o.note} className="flex flex-col gap-1.5 rounded-[20px] border border-divider bg-white p-6">
              <p className="flex flex-wrap items-baseline gap-2 font-num">
                <span className="text-[40px] leading-tight font-semibold tracking-[-0.02em] text-ink">{o.value}</span>
                <Metric name={o.unit} className="text-[13px] font-medium text-text2" />
              </p>
              <p className="text-[13px] leading-5 text-text2">{o.note}</p>
              <Link to={`/research/${o.report}`} className="mt-2.5 flex items-center gap-1.5 border-t border-divider pt-3 text-[12px] text-muted transition-colors hover:text-[#a8733f]">
                {o.source}
                <span aria-hidden className="font-num">
                  →
                </span>
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Compare({ onAsk }: { onAsk: () => void }) {
  const [stage, setStage] = useState<keyof typeof COMPARE_STAGES>('rerank');
  const data = COMPARE_STAGES[stage];
  return (
    <section id="compare" aria-labelledby="compare-title" className={section}>
      <div className={wrap}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
          <SectionHead
            id="compare-title"
            eyebrow="开源项目对比"
            title="同一份数据上，对比腾讯开源的 WeKnora"
            desc="WeKnora 在隔离环境中导入同样的 5,183 篇文档，使用同名稠密模型，按源文档用同一套公式评分；双方再各取前 30 个 chunk，接入同一个文本重排模型。"
          />
          <span className="flex-1" />
          <span className="self-start rounded-full border border-divider bg-white px-3 py-1.5 font-num text-[12px] font-medium text-text2 lg:self-auto">R12 · R13 · 2026-09-29</span>
        </div>

        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {ADVANTAGES.map((a) => (
            <div key={a.title} className={cn('flex flex-col gap-2 rounded-[20px] border border-divider p-[26px]', a.strong ? 'bg-brand-soft' : 'bg-white')}>
              <p className="flex items-baseline gap-2.5 font-num">
                <span className="text-[44px] leading-tight font-semibold tracking-[-0.02em] text-ink">{a.value}</span>
                <span className="text-[14px] font-medium text-muted">{a.sub}</span>
              </p>
              <p className="text-[13.5px] font-medium text-ink">{a.title}</p>
              <p className="text-[13px] leading-5 text-text2">{a.desc}</p>
            </div>
          ))}
        </div>

        <div className="mt-5 flex flex-col overflow-hidden rounded-[20px] border leading-[normal] border-divider bg-white shadow-[0_8px_28px_0_rgba(28,26,20,0.05)] lg:flex-row">
          <div className="flex flex-col gap-5 border-b border-divider p-6 md:p-8 lg:w-[480px] lg:shrink-0 lg:border-r lg:border-b-0">
            <h3 className="text-[15px] font-medium text-ink">{data.label}</h3>
            <div className="flex gap-4 font-num text-[12.5px] text-text2">
              <span className="flex items-center gap-1.5">
                <span aria-hidden className="size-2.5 rounded-[2px] bg-[#b87a3a]" />
                LinkRag
              </span>
              <span className="flex items-center gap-1.5">
                <span aria-hidden className="size-2.5 rounded-[2px] bg-[#c9c8c0]" />
                WeKnora
              </span>
            </div>
            {data.bars.map(([k, a, b, d]) => (
              <div key={k} role="group" aria-label={`${k}：LinkRag ${a}，WeKnora ${b}，差值 ${d}`} className="flex max-w-[380px] flex-col gap-[5px]">
                <div className="flex text-[12.5px] font-medium text-ink">
                  <Metric name={k} className="font-num" />
                  <span className="flex-1" />
                  <span className="font-num text-[12px] text-[#a8733f]">{d}</span>
                </div>
                <div className="flex items-center gap-2.5">
                  <Bar value={+a} strong className="flex-1" />
                  <span className="w-12 font-num text-[12.5px] font-semibold text-ink">{a}</span>
                </div>
                <div className="flex items-center gap-2.5">
                  <Bar value={+b} className="flex-1" />
                  <span className="w-12 font-num text-[12.5px] text-text2">{b}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="flex min-w-0 flex-1 flex-col p-6 md:p-8">
            <div className="flex items-center gap-3">
              <h3 className="text-[15px] font-medium text-ink">完整指标</h3>
              <span className="flex-1" />
              <div role="tablist" aria-label="评测阶段" className="flex gap-0.5 rounded-full bg-soft p-[3px]">
                {(Object.keys(COMPARE_STAGES) as (keyof typeof COMPARE_STAGES)[]).map((k) => (
                  <button
                    key={k}
                    type="button"
                    role="tab"
                    aria-selected={stage === k}
                    onClick={() => setStage(k)}
                    className={cn('rounded-full px-3 py-[5px] text-[12px] font-medium transition-colors', stage === k ? 'bg-white text-ink shadow-[0_1px_3px_0_rgba(28,26,20,0.08)]' : 'text-muted hover:text-ink')}
                  >
                    {COMPARE_STAGES[k].label}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-[18px] overflow-x-auto">
              <table key={stage} className="w-full min-w-[480px] animate-tab-in text-[13px]">
                <thead>
                  <tr className="border-b border-divider text-[11.5px]">
                    <th scope="col" className="px-2.5 pb-2.5 text-left font-normal text-muted">
                      指标
                    </th>
                    <th scope="col" className="px-2.5 pb-2.5 text-right font-num font-medium text-[#a8733f]">
                      LinkRag
                    </th>
                    <th scope="col" className="px-2.5 pb-2.5 text-right font-num font-normal text-muted">
                      WeKnora
                    </th>
                    <th scope="col" className="px-2.5 pb-2.5 text-right font-normal text-muted">
                      差值
                    </th>
                  </tr>
                </thead>
                <tbody className="font-num">
                  {data.table.map(([k, a, b, d]) => (
                    <tr key={k} className="border-b border-divider">
                      <th scope="row" className="px-2.5 py-[11px] text-left font-sans font-normal text-ink">
                        <Metric name={k} />
                      </th>
                      <td className="px-2.5 py-[11px] text-right font-semibold text-ink">{a}</td>
                      <td className="px-2.5 py-[11px] text-right text-text2">{b}</td>
                      <td className={cn('px-2.5 py-[11px] text-right text-[12.5px] font-medium', d === '持平' ? 'font-sans text-muted' : 'text-[#a8733f]')}>{d}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3.5 text-[11.5px] leading-[18px] text-muted">差值单位为百分点（题数除外）。基于单次 300 题评测，逐题结果和统计区间见 R12、R13 报告。</p>
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-3">
          {WHY.map((w) => (
            <div key={w.title} className="flex flex-col gap-2 rounded-[14px] border border-divider bg-white p-[22px]">
              <p className="text-[14px] font-medium text-ink">{w.title}</p>
              <p className="text-[13px] leading-[21px] text-text2">{w.desc}</p>
            </div>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2.5 rounded-[12px] border border-divider bg-[#fbfbf9] px-[18px] py-3.5">
          <span className="text-[13px] font-medium text-ink">后续对比</span>
          {PLANNED.map((p) => (
            <span key={p} className="rounded-full border border-divider bg-white px-2.5 py-1 font-num text-[12px] font-medium text-muted">
              {p} · 计划中
            </span>
          ))}
          <span className="flex-1" />
          <button type="button" onClick={onAsk} className="group flex items-center gap-1 text-[12.5px] font-medium text-[#a8733f] hover:underline">
            提交对比请求
            <span aria-hidden className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5">
              ↗
            </span>
          </button>
        </div>
      </div>
    </section>
  );
}

function Ablation() {
  return (
    <section id="ablation" aria-labelledby="ablation-title" className={cn(section, 'bg-white')}>
      <div className={wrap}>
        <SectionHead id="ablation-title" eyebrow="逐轮消融" title="从旧基线到文本重排，每一轮做了什么" desc="R09 用旧四域小语料，R10–R13 用同一份 SciFact 300 题。两组数据集、语料规模和检索实现都不同，数字只在同一组内可比。" />

        <div className="mt-8 flex flex-col gap-3.5 rounded-[20px] border border-divider bg-[#fbfbf9] p-5 leading-[normal] md:p-7">
          <div className="flex items-center gap-3">
            <div className="flex flex-col gap-1">
              <h3 className="text-[15px] font-medium text-ink">R10 · SciFact 六种召回配置</h3>
              <p className="text-[12px] text-muted">5,183 篇文档 · 300 题 · 同一次逐路候选缓存 · 三路加权 0.70 / 0.15 / 0.15 · RRF k=60</p>
            </div>
            <span className="flex-1" />
            <Metric name="Recall@10" className="hidden font-num text-[12px] font-medium text-text2 sm:inline-flex" />
          </div>
          {R10_CONFIGS.map((c) => (
            <div key={c.label} className="flex items-center gap-3.5">
              <span className={cn('w-[118px] shrink-0 text-[13px] md:w-[170px]', c.strong ? 'font-medium text-ink' : 'text-text2')}>{c.label}</span>
              <Bar value={c.value} strong={c.strong} height={16} className="max-w-[620px] flex-1 rounded-[4px]" />
              <span className={cn('w-12 font-num text-[13px] text-ink', c.strong && 'font-semibold')}>{c.value.toFixed(4)}</span>
            </div>
          ))}
          <p className="text-[12.5px] leading-5 text-text2">三路加权的 Recall@10 最高；稠密 + BM25 在 Recall@1、nDCG@10、MRR@10 上略高。三路 RRF 明显低于加权融合。</p>
        </div>

        <h3 className="mt-8 text-[15px] font-medium text-ink">轮次时间线</h3>
        <ol className="mt-4 flex flex-col">
          {ROUNDS.map((r, i) => (
            <li key={r.id} className="flex gap-4 pb-4 last:pb-0 md:gap-6">
              <div className="flex w-10 shrink-0 flex-col items-center">
                <span className={cn('flex size-10 items-center justify-center rounded-full font-num text-[11px] font-semibold', r.latest ? 'bg-brand text-white' : 'border border-line bg-white text-ink')}>{r.id}</span>
                {i < ROUNDS.length - 1 && <span aria-hidden className="w-px flex-1 bg-line" />}
              </div>
              <Link
                to={`/research/${r.report}`}
                className="group flex min-w-0 flex-1 flex-col gap-4 rounded-[14px] leading-[normal] border border-divider bg-[#fbfbf9] px-5 py-5 transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-line hover:bg-white hover:shadow-[0_10px_28px_-8px_rgba(28,26,20,0.14)] md:px-6 lg:flex-row lg:items-center lg:gap-6"
              >
                <div className="flex min-w-0 flex-col gap-1.5 lg:w-[440px] lg:shrink-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="text-[15px] font-medium text-ink">{r.title}</span>
                    <span className="font-num text-[11.5px] text-muted">{r.date}</span>
                  </p>
                  <p className="text-[13px] text-text2">{r.what}</p>
                  <p className="text-[12px] text-muted">{r.data}</p>
                </div>
                <span className="hidden flex-1 lg:block" />
                <div className="flex flex-col gap-1 lg:items-end">
                  <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-num">
                    <span className="text-[12px] text-muted">{r.metric}</span>
                    <span className="text-[14px] text-text2">{r.from}</span>
                    <span aria-hidden className="text-[13px] text-muted">
                      →
                    </span>
                    <span className="text-[20px] font-semibold text-ink">{r.to}</span>
                    <span className="rounded-full bg-[#fdf3e7] px-2.5 py-1 text-[12.5px] font-medium text-[#a8733f] lg:hidden">{r.delta}</span>
                  </p>
                  <p className="text-[11.5px] text-muted">{r.path}</p>
                </div>
                <div className="hidden w-[76px] shrink-0 justify-end lg:flex">
                  <span className="rounded-full bg-[#fdf3e7] px-2.5 py-1 font-num text-[12.5px] font-medium text-[#a8733f]">{r.delta}</span>
                </div>
                <div className="flex flex-col gap-1.5 lg:w-[210px] lg:shrink-0">
                  <p className="text-[12px] leading-[18px] text-text2">{r.note}</p>
                  <span className="text-[12.5px] font-medium text-[#a8733f]">
                    报告 <span className="inline-block transition-transform group-hover:translate-x-0.5">→</span>
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Reports({ version }: { version: string }) {
  const [query, setQuery] = useState('');
  const [type, setType] = useState<ReportType | 'all'>('all');
  const [order, setOrder] = useState<'new' | 'old'>('new');
  const [open, setOpen] = useState<string | null>(null);

  const scoped = useMemo(() => REPORTS.filter((r) => version === 'all' || r.version === version), [version]);
  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = scoped.filter((r) => (type === 'all' || r.type === type) && (!q || [r.title, r.desc, r.dataset, r.key, ...r.config.map((c) => c[1])].join(' ').toLowerCase().includes(q)));
    return order === 'new' ? rows : [...rows].reverse();
  }, [scoped, query, type, order]);
  const count = (t: ReportType) => scoped.filter((r) => r.type === t).length;

  return (
    <section id="reports" aria-labelledby="reports-title" className={section}>
      <div className={wrap}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
          <SectionHead id="reports-title" eyebrow="历史报告" title="每一次评测都留档" desc="按时间倒序。每份报告包含数据集、配置、逐题结果和当时的代码版本。" />
          <span className="flex-1" />
          <label className="flex w-full items-center gap-2 rounded-full border border-line bg-white px-3.5 py-[9px] text-muted focus-within:border-brand lg:w-[260px]">
            <span aria-hidden className="text-[14px]">
              ⌕
            </span>
            <span className="sr-only">搜索报告</span>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索报告、数据集、commit" className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-muted" />
          </label>
        </div>

        <div className="mt-7 flex flex-wrap items-center gap-2">
          <div role="group" aria-label="报告类型" className="flex flex-wrap gap-2">
            {(['all', ...REPORT_TYPES] as const).map((t) => {
              const n = t === 'all' ? scoped.length : count(t);
              const on = type === t;
              return (
                <button
                  key={t}
                  type="button"
                  aria-pressed={on}
                  disabled={n === 0 && !on}
                  onClick={() => setType(t)}
                  className={cn(
                    'rounded-full border px-3.5 py-[7px] text-[12.5px] font-medium transition-colors',
                    on ? 'border-brand bg-brand text-white' : 'border-divider bg-white text-text2 hover:border-line hover:bg-[#fbfbf9] hover:text-ink',
                    'disabled:cursor-not-allowed disabled:border-dashed disabled:text-faint disabled:hover:bg-white',
                  )}
                >
                  {t === 'all' ? '全部' : t}
                  {n === 0 && <span className="ml-1 font-num">0</span>}
                </button>
              );
            })}
          </div>
          <span className="flex-1" />
          <Dropdown
            label="排序方式"
            value={order}
            onChange={(v) => setOrder(v as 'new' | 'old')}
            options={[
              { value: 'new', label: '最新' },
              { value: 'old', label: '最早' },
            ]}
          />
        </div>

        <div className="mt-4 overflow-hidden rounded-[20px] border border-divider bg-white leading-[normal]">
          <div aria-hidden className="hidden border-b border-divider bg-[#fbfbf9] px-7 py-3.5 text-[11.5px] text-muted lg:flex">
            <span className="w-[110px]">日期</span>
            <span className="w-[440px]">报告</span>
            <span className="w-[100px]">类型</span>
            <span className="w-[200px]">数据集</span>
            <span className="w-[200px]">关键结果</span>
            <span className="w-[100px]">状态</span>
          </div>
          {list.length === 0 ? (
            <p className="px-7 py-14 text-center text-[13px] text-muted">没有匹配的报告，换个关键词或筛选条件试试。</p>
          ) : (
            <ul>
              {list.map((r) => (
                <ReportRow key={r.id} r={r} open={open === r.id} onToggle={() => setOpen((o) => (o === r.id ? null : r.id))} />
              ))}
            </ul>
          )}
        </div>

        <div className="mt-4 flex flex-col gap-2 md:flex-row md:items-center">
          <p className="text-[12.5px] text-muted">完整轮次登记与 R01–R08 历史实验见实验台账；12 题 Realistic Blind 诊断口径不同，不计入上表。</p>
          <span className="flex-1" />
          <a href={RELEASES_URL} {...ext} className="text-[13px] font-medium text-[#a8733f] hover:underline">
            查看全部归档 ↗
          </a>
        </div>
      </div>
    </section>
  );
}

/** 历史报告行（S1）：悬停高亮 → 点击箭头在列表内展开，再点「查看完整报告」进入详情 */
function ReportRow({ r, open, onToggle }: { r: Report; open: boolean; onToggle: () => void }) {
  const [copy, copied] = useCopy();
  const paneId = useId();
  return (
    <li className={cn('border-b border-divider last:border-b-0', open ? 'bg-brand-soft' : r.latest && 'bg-brand-soft/60')}>
      <div className={cn('group flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-[18px] transition-colors md:px-7 lg:flex-nowrap lg:gap-0', !open && 'hover:bg-[#fbfbf9]')}>
        <span className="order-1 font-num text-[13px] text-text2 lg:w-[110px]">{r.date}</span>
        <div className="order-3 flex w-full min-w-0 flex-col gap-1 lg:order-2 lg:w-[440px] lg:pr-6">
          <Link to={`/research/${r.id}`} className="truncate text-[14px] font-medium text-ink hover:text-[#a8733f]">
            {r.title}
          </Link>
          <p className="truncate text-[12.5px] text-muted">{r.desc}</p>
        </div>
        <span className="order-2 lg:order-3 lg:w-[100px]">
          <span className="rounded-full bg-soft px-2.5 py-1 text-[12px] font-medium whitespace-nowrap text-text2">{r.type}</span>
        </span>
        <span className="order-4 text-[12.5px] text-text2 lg:w-[200px]">{r.dataset}</span>
        <span className="order-5 font-num text-[12.5px] font-medium text-ink lg:w-[200px]">{r.key}</span>
        <span className="order-6 lg:w-[100px]">
          {r.latest ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#efd9bd] bg-[#fdf3e7] px-2.5 py-1 text-[12px] font-medium text-[#a8733f]">
              <span aria-hidden className="size-1.5 rounded-full bg-[#b87a3a]" />
              最新
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-divider bg-white px-2.5 py-1 text-[12px] font-medium text-muted">
              <span aria-hidden className="size-1.5 rounded-full bg-faint" />
              已归档
            </span>
          )}
        </span>
        <span className="order-7 flex-1" />
        <button
          type="button"
          aria-expanded={open}
          aria-controls={paneId}
          aria-label={open ? `收起 ${r.title}` : `展开 ${r.title}`}
          onClick={onToggle}
          className={cn(
            'order-8 flex size-8 shrink-0 items-center justify-center rounded-full border font-num text-[14px] font-medium transition-colors',
            open ? 'border-brand bg-brand text-white' : 'border-transparent text-muted group-hover:border-line group-hover:bg-white group-hover:text-ink',
          )}
        >
          <span aria-hidden className={cn('transition-transform', open && 'rotate-180')}>
            ⌄
          </span>
        </button>
      </div>
      {open && (
        <div id={paneId} className="flex animate-tab-in flex-col gap-5 px-5 pt-1 pb-6 md:px-7 lg:flex-row lg:pl-[138px]">
          <div className="flex flex-1 flex-col gap-2.5 rounded-[14px] border border-divider bg-white p-5">
            <p className="text-[12px] font-medium text-[#a8733f]">摘要</p>
            {r.cols[1] && (
              <p className="flex font-num text-[11.5px] text-muted">
                <span className="w-[120px]" />
                <span className="w-[90px] text-right">{r.cols[0]}</span>
                <span className="w-[90px] text-right">{r.cols[1]}</span>
              </p>
            )}
            {r.metrics.map(([k, a, b, d]) => (
              <p key={k} className="flex items-center font-num text-[12.5px]">
                <span className="w-[120px] text-text2">{k}</span>
                <span className="w-[90px] text-right font-semibold text-ink">{a}</span>
                {b !== undefined && <span className="w-[90px] text-right text-muted">{b}</span>}
                {d && <span className={cn('w-[60px] text-right text-[12px] font-medium', d.startsWith('−') ? 'text-[#c86a5a]' : 'text-[#a8733f]')}>{d}</span>}
              </p>
            ))}
          </div>
          <div className="flex flex-1 flex-col gap-2.5 rounded-[14px] border border-divider bg-white p-5">
            <p className="text-[12px] font-medium text-[#a8733f]">配置</p>
            {r.config.map(([k, v]) => (
              <p key={k} className="flex text-[12.5px]">
                <span className="w-20 shrink-0 text-muted">{k}</span>
                <span className="min-w-0 font-num text-ink">{v}</span>
              </p>
            ))}
          </div>
          <div className="flex flex-col gap-2 lg:w-[200px] lg:shrink-0">
            <Link to={`/research/${r.id}`} className={cn(pill.primary, 'justify-between px-[15px] py-[9px] text-[13px]')}>
              查看完整报告 <span aria-hidden>→</span>
            </Link>
            <RawDownload href={r.rawUrl} filename={`${r.id}.json`} className={cn(pill.secondary, 'justify-between px-[15px] py-[9px] text-[13px]')}>
              下载原始 JSON <span aria-hidden className="text-muted">↓</span>
            </RawDownload>
            <button type="button" onClick={() => copy(reproCommand(r).replace(/^\$ /, ''), '复现命令已复制到剪贴板')} className={cn(pill.secondary, 'justify-between px-[15px] py-[9px] text-[13px]')}>
              {copied ? '已复制' : '复制复现命令'}
              <span aria-hidden className={copied ? 'text-[#a8733f]' : 'text-muted'}>
                {copied ? '✓' : '⧉'}
              </span>
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

function Repro() {
  const [tab, setTab] = useState(CODE_TABS[0].id);
  const [copy, copied] = useCopy();
  const cur = CODE_TABS.find((t) => t.id === tab) ?? CODE_TABS[0];
  const tone = { c: 'text-muted', i: 'text-ink', ok: 'text-[#a8733f]', o: 'text-text2' };
  return (
    <section id="repro" aria-labelledby="repro-title" className={cn(section, 'bg-brand-soft md:pb-24')}>
      <div className={cn(wrap, 'flex flex-col gap-10 lg:flex-row lg:gap-14')}>
        <div className="flex flex-col lg:w-[440px] lg:shrink-0">
          <SectionHead id="repro-title" eyebrow="复现指南" title="从公开数据包开始，逐轮复现" />
          <p className="mt-3.5 text-[15px] leading-[25px] text-text2">每一轮都有独立脚本、固定随机种子和原始产物。审计文件记录数据包哈希、三库入库数和逐题排名，可以核对每一个数字。</p>
          <dl className="mt-7">
            {REPRO_FACTS.map(([k, v]) => (
              <div key={k} className="flex border-t border-divider py-3 text-[13px]">
                <dt className="w-[110px] shrink-0 text-muted">{k}</dt>
                <dd className="min-w-0 font-medium text-ink">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-6 flex flex-wrap gap-2.5">
            <a href={GITHUB_URL} {...ext} className={cn(pill.primary, btn.lg)}>
              打开 GitHub 仓库 <span aria-hidden>↗</span>
            </a>
            <RawDownload href={ALL_RAW_RESULTS_URL} disabledTitle="全部原始结果暂未公开" className={cn(pill.secondary, btn.lg)}>
              下载原始结果合集 <span aria-hidden className="text-muted">↓</span>
            </RawDownload>
          </div>
        </div>
        <div className="min-w-0 flex-1 overflow-hidden rounded-[20px] border border-divider bg-white shadow-[0_12px_36px_0_rgba(28,26,20,0.06)]">
          <div className="flex items-center gap-1.5 border-b border-divider bg-[#fbfbf9] px-[18px] py-3">
            <div role="tablist" aria-label="复现代码" className="flex gap-1.5">
              {CODE_TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={tab === t.id}
                  onClick={() => setTab(t.id)}
                  className={cn('rounded-full border px-3 py-[5px] text-[12px] font-medium transition-colors', t.mono && 'font-mono', tab === t.id ? 'border-divider bg-white text-ink' : 'border-transparent text-muted hover:text-ink')}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <span className="flex-1" />
            <button type="button" onClick={() => copy(cur.lines.map((l) => l[1]).join('\n'))} className={cn('text-[12px] transition-colors', copied ? 'text-[#a8733f]' : 'text-muted hover:text-ink')}>
              {copied ? '✓ 已复制' : '复制'}
            </button>
          </div>
          <pre key={tab} role="tabpanel" aria-label={cur.label} className="animate-tab-in overflow-x-auto px-6 pt-[22px] pb-6 font-mono text-[12.5px] leading-[26px]">
            {cur.lines.map(([t, text], i) => (
              <div key={i} className={tone[t]}>
                {text || ' '}
              </div>
            ))}
          </pre>
        </div>
      </div>
    </section>
  );
}

/** 提交对比请求（S6）：站内弹窗，提交时带上表单内容跳到 GitHub 新建 Issue */
function CompareRequestDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('');
  const [repo, setRepo] = useState('');
  const [sets, setSets] = useState<string[]>(['SciFact']);
  const [note, setNote] = useState('');
  const first = useRef<HTMLInputElement>(null);
  const titleId = useId();
  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toggle = (s: string) => setSets((v) => (v.includes(s) ? v.filter((x) => x !== s) : [...v, s]));
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const body = [`**项目名称**：${name}`, `**仓库地址**：${repo}`, `**希望使用的数据集**：${sets.join('、') || '未选择'}`, '', note && `**备注**：\n${note}`].filter(Boolean).join('\n');
    const url = `${COMPARE_ISSUE_URL}?${new URLSearchParams({ title: `[对比请求] ${name}`, body, labels: 'benchmark' })}`;
    window.open(url, '_blank', 'noopener,noreferrer');
    onClose();
  };
  const input = 'w-full rounded-[10px] border border-line bg-white px-3 py-2.5 text-[13px] text-ink outline-none transition-shadow placeholder:text-muted focus:border-[#b87a3a] focus:shadow-[0_0_0_3px_rgba(184,122,58,0.18)]';

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[rgba(29,29,27,0.28)] px-4 py-10" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form role="dialog" aria-modal="true" aria-labelledby={titleId} onSubmit={submit} className="flex w-full max-w-[520px] animate-rise-in flex-col gap-[18px] rounded-[20px] bg-white p-7 shadow-[0_20px_48px_0_rgba(28,26,20,0.12)]">
        <div className="flex items-start gap-3">
          <div className="flex flex-col gap-1">
            <h2 id={titleId} className="font-serif text-[22px] font-semibold text-ink">
              提交对比请求
            </h2>
            <p className="text-[13px] text-muted">我们会按同一口径（同语料、同稠密模型、同评分）加入对比。</p>
          </div>
          <span className="flex-1" />
          <button type="button" aria-label="关闭" onClick={onClose} className="flex size-8 shrink-0 items-center justify-center rounded-full bg-soft text-text2 hover:bg-active">
            <X className="size-3.5" />
          </button>
        </div>
        <label className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-medium text-ink">项目名称</span>
          <input ref={first} required value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 RAGFlow" className={input} />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-medium text-ink">仓库地址</span>
          <input required type="url" value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="https://github.com/…" className={cn(input, 'font-num')} />
        </label>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-[12.5px] font-medium text-ink">希望使用的数据集</legend>
          <div className="flex flex-wrap gap-2">
            {['SciFact', '旧四域基线', '其他（在备注里说明）'].map((s) => {
              const on = sets.includes(s);
              return (
                <button key={s} type="button" aria-pressed={on} onClick={() => toggle(s)} className={cn('rounded-full border px-3 py-1.5 text-[12.5px] font-medium transition-colors', on ? 'border-[#efd9bd] bg-brand-soft text-[#a8733f]' : 'border-divider bg-white text-text2 hover:border-line')}>
                  {on && '✓ '}
                  {s}
                </button>
              );
            })}
          </div>
        </fieldset>
        <label className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-medium text-ink">备注（可选）</span>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="例如希望开启的配置、版本号…" className={cn(input, 'resize-none')} />
        </label>
        <div className="flex flex-wrap items-center gap-2.5 pt-2">
          <p className="text-[12px] text-muted">将跳转到 GitHub 生成一条公开 Issue</p>
          <span className="flex-1" />
          <button type="button" onClick={onClose} className={cn(pill.secondary, 'px-4 py-2.5 text-[13px]')}>
            取消
          </button>
          <button type="submit" className={cn(pill.primary, 'gap-[7px] px-4 py-2.5 text-[13px]')}>
            提交 <span aria-hidden>→</span>
          </button>
        </div>
      </form>
    </div>
  );
}
