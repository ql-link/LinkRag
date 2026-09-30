import { Link, Navigate, useParams } from 'react-router-dom';

import { cn } from '@/lib/cn';
import { GITHUB_URL, pill } from '@/pages/landing/shared';
import { PublicShell, SCROLL_ROOT_ID } from '@/pages/landing/SiteChrome';

import { btn, ext, Metric, RawDownload, useCopy, useScrollSpy } from './components';
import { findReport, relatedReports, reproCommand, type Report } from './data';

/**
 * 设计稿「06 落地页」L7 评测报告详情 · 桌面：
 * 左侧粘性目录（滚动高亮）+ 摘要 / 评测环境 / 结果 / 局限与说明 / 复现。
 */
const TOC = [
  { id: 'summary', label: '摘要' },
  { id: 'env', label: '评测环境' },
  { id: 'result', label: '结果' },
  { id: 'limits', label: '局限与说明' },
  { id: 'repro', label: '复现' },
];

/** 分组柱色：最后一项为主系列（LinkRag / 本轮方案） */
const SERIES = ['#d8d6cd', '#a9a79d', '#b87a3a'];
const seriesColor = (i: number, n: number) => SERIES[SERIES.length - n + i] ?? SERIES[i % SERIES.length];

export default function ReportPage() {
  const { reportId } = useParams();
  const report = findReport(reportId);
  if (!report) return <Navigate to="/research#reports" replace />;
  return (
    <PublicShell>
      <ReportBody key={report.id} r={report} />
    </PublicShell>
  );
}

function ReportBody({ r }: { r: Report }) {
  const active = useScrollSpy(
    TOC.map((t) => t.id),
    SCROLL_ROOT_ID,
  );
  const related = relatedReports(r);
  const [copy, copied] = useCopy();
  const cmd = reproCommand(r);

  return (
    <div className="mx-auto flex max-w-[1440px] gap-14 px-5 pt-8 pb-24 md:px-[100px] md:pt-12">
      <aside className="hidden w-[200px] shrink-0 lg:block">
        <div className="sticky top-[105px] flex flex-col gap-1">
          <Link to="/research#reports" className="text-[13px] text-muted hover:text-ink">
            ← 返回评测中心
          </Link>
          <p className="mt-6 mb-2 text-[12px] font-medium text-muted">本页内容</p>
          <nav aria-label="本页目录" className="flex flex-col">
            {TOC.map((t) => (
              <a
                key={t.id}
                href={`#${t.id}`}
                aria-current={active === t.id ? 'true' : undefined}
                className={cn('px-3 py-[7px] text-[13.5px] transition-colors', active === t.id ? 'border-l-2 border-[#b87a3a] font-medium text-ink' : 'border-l border-divider text-text2 hover:text-ink')}
              >
                {t.label}
              </a>
            ))}
          </nav>
          {related.length > 0 && (
            <div className="mt-7 flex flex-col gap-2 rounded-[14px] border border-divider bg-white p-4">
              <p className="text-[12px] font-medium text-muted">同类报告</p>
              {related.map((x) => (
                <Link key={x.id} to={`/research/${x.id}`} className="group flex flex-col gap-0.5">
                  <span className="font-num text-[11px] text-muted">{x.date}</span>
                  <span className="text-[12.5px] text-text2 group-hover:text-ink">{x.title}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </aside>

      <article className="flex min-w-0 flex-1 flex-col">
        <Link to="/research#reports" className="mb-5 text-[13px] text-muted hover:text-ink lg:hidden">
          ← 返回评测中心
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-soft px-2.5 py-1 text-[12px] font-medium text-text2">{r.type}</span>
          <span className="flex items-center gap-1.5 rounded-full border border-divider bg-white px-2.5 py-1 font-num text-[12px] font-medium text-text2">
            <span aria-hidden className={cn('size-1.5 rounded-full', r.latest ? 'bg-[#b87a3a]' : 'bg-green')} />
            {r.latest ? '最新' : 'clean run'}
          </span>
          <span className="font-num text-[12.5px] text-muted">{r.date}</span>
          <span className="font-num text-[12.5px] text-muted">· {r.version}</span>
        </div>

        <div className="mt-[18px] flex flex-col gap-5 xl:flex-row xl:items-end">
          <div className="flex max-w-[620px] flex-col gap-3">
            <h1 className="font-serif text-[clamp(30px,3.6vw,40px)] leading-tight font-semibold tracking-[-0.01em] text-ink">{r.title}</h1>
            <p className="text-[15px] leading-[25px] text-text2">{r.lead}</p>
          </div>
          <span className="hidden flex-1 xl:block" />
          <div className="flex shrink-0 gap-2">
            <RawDownload href={r.rawUrl} filename={`${r.id}.json`} className={cn(pill.secondary, btn.md)}>
              原始 JSON <span aria-hidden className="text-muted">↓</span>
            </RawDownload>
            <a href="#repro" className={cn(pill.primary, btn.md)}>
              复现此报告 <span aria-hidden>↗</span>
            </a>
          </div>
        </div>

        <section id="summary" aria-label="摘要" className="mt-8 flex scroll-mt-[105px] flex-col gap-2.5 rounded-[14px] bg-brand-soft p-6">
          <p className="text-[13px] font-medium text-[#a8733f]">摘要</p>
          <ul className="flex flex-col gap-2.5">
            {r.points.map((p) => (
              <li key={p} className="flex gap-2.5 text-[14px] leading-[23px] text-ink">
                <span aria-hidden className="mt-[9px] size-[5px] shrink-0 rounded-full bg-[#b87a3a]" />
                {p}
              </li>
            ))}
          </ul>
        </section>

        <H2 id="env">评测环境</H2>
        <dl className="overflow-hidden rounded-[14px] border border-divider bg-white text-[13px]">
          {r.env.map(([k, v], i) => (
            <div key={k} className={cn('flex flex-col gap-1 px-5 py-3 sm:flex-row', i % 2 === 1 && 'bg-[#fbfbf9]')}>
              <dt className="shrink-0 text-muted sm:w-[130px]">{k}</dt>
              <dd className="min-w-0 font-num text-ink">{v}</dd>
            </div>
          ))}
        </dl>

        <H2 id="result">结果</H2>
        <ResultChart r={r} />
        <div className="mt-4 overflow-x-auto rounded-[14px] border border-divider bg-white">
          <table className="w-full min-w-[420px] text-[13px]">
            <thead>
              <tr className="border-b border-divider bg-[#fbfbf9] text-[11.5px] text-muted">
                <th scope="col" className="px-5 py-2.5 text-left font-normal">
                  指标
                </th>
                <th scope="col" className="px-5 py-2.5 text-right font-num font-medium text-[#a8733f]">
                  {r.cols[0]}
                </th>
                {r.cols[1] && (
                  <>
                    <th scope="col" className="px-5 py-2.5 text-right font-num font-normal">
                      {r.cols[1]}
                    </th>
                    <th scope="col" className="px-5 py-2.5 text-right font-normal">
                      差值
                    </th>
                  </>
                )}
              </tr>
            </thead>
            <tbody className="font-num">
              {r.metrics.map(([k, a, b, d]) => (
                <tr key={k} className="border-b border-divider last:border-b-0">
                  <th scope="row" className="px-5 py-3 text-left font-sans font-normal text-ink">
                    <Metric name={k} />
                  </th>
                  <td className="px-5 py-3 text-right font-semibold text-ink">{a}</td>
                  {r.cols[1] && (
                    <>
                      <td className="px-5 py-3 text-right text-text2">{b}</td>
                      <td className={cn('px-5 py-3 text-right text-[12.5px] font-medium', d?.startsWith('−') ? 'text-[#c86a5a]' : 'text-[#a8733f]')}>{d}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <H2 id="limits">局限与说明</H2>
        <ul className="flex max-w-[900px] flex-col gap-1.5">
          {r.limits.map((l) => (
            <li key={l} className="text-[14px] leading-6 text-text2">
              · {l}
            </li>
          ))}
        </ul>

        <section id="repro" aria-label="复现" className="mt-10 flex scroll-mt-[105px] flex-col gap-4 rounded-[14px] bg-soft px-6 py-5 sm:flex-row sm:items-center">
          <div className="flex min-w-0 flex-col gap-1.5">
            <p className="text-[14px] font-medium text-ink">复现此报告</p>
            <code className="overflow-x-auto font-mono text-[12.5px] whitespace-nowrap text-text2">{cmd}</code>
          </div>
          <span className="hidden flex-1 sm:block" />
          {r.command ? (
            <button type="button" onClick={() => copy(r.command!, '复现命令已复制到剪贴板')} className={cn(pill.secondary, btn.md, 'shrink-0')}>
              {copied ? '已复制' : '复制命令'}
              <span aria-hidden className={copied ? 'text-[#a8733f]' : 'text-muted'}>
                {copied ? '✓' : '⧉'}
              </span>
            </button>
          ) : (
            <a href={GITHUB_URL} {...ext} className={cn(pill.secondary, btn.md, 'shrink-0')}>
              查看仓库 <span aria-hidden>↗</span>
            </a>
          )}
        </section>
      </article>
    </div>
  );
}

function H2({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="mt-10 mb-4 scroll-mt-[105px] font-serif text-[22px] font-semibold text-ink">
      {children}
    </h2>
  );
}

/** 分组柱状图：纵轴从 0 开始，每组最高值加粗 */
function ResultChart({ r }: { r: Report }) {
  const chart = r.chart;
  if (!chart) return null;
  const n = chart.legend.length;
  const H = 180;
  return (
    <figure className="flex flex-col gap-5 rounded-[20px] border border-divider bg-white p-6 md:p-7">
      <div className="flex flex-wrap gap-[18px]">
        {chart.legend.map((l, i) => (
          <span key={l} className="flex items-center gap-1.5 text-[12.5px] text-text2">
            <span aria-hidden style={{ background: seriesColor(i, n) }} className="size-2.5 rounded-[2px]" />
            {l}
          </span>
        ))}
      </div>
      <div className="flex items-end overflow-x-auto">
        {chart.groups.map((g) => {
          const max = Math.max(...g.values);
          return (
            <div key={g.label} role="img" aria-label={`${g.label}：${g.values.map((v, i) => `${chart.legend[i]} ${v}`).join('，')}`} className="flex min-w-[88px] flex-1 flex-col items-center gap-2.5">
              <div className="flex items-end gap-0.5">
                {g.values.map((v, i) => (
                  <div key={i} className="flex flex-col items-center gap-1">
                    <span className={cn('font-num text-[10.5px]', v === max && n > 1 ? 'font-semibold text-ink' : 'text-muted')}>{v >= 1 ? v.toFixed(2) : v.toFixed(3)}</span>
                    <span style={{ height: Math.max(2, v * H), background: seriesColor(i, n) }} className="block w-7 rounded-t-[4px]" />
                  </div>
                ))}
              </div>
              <span className="w-full border-t border-divider pt-2 text-center font-num text-[12px] font-medium text-text2">{g.label}</span>
            </div>
          );
        })}
      </div>
      <figcaption className="text-[12px] text-muted">纵轴从 0 开始。{n > 1 && '各指标下数值最高者加粗。'}</figcaption>
    </figure>
  );
}
