import { ArrowDown, ArrowUp, Cpu, Plus, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { PageHeader } from '@/components/PageHeader';
import { SectionLabel } from '@/components/SectionLabel';
import { Button } from '@/components/ui/Button';
import { Chip, type Tone } from '@/components/ui/Chip';
import { PageLoading } from '@/components/ui/Loading';
import { useToast } from '@/contexts/ToastContext';
import { PageColumn } from '@/layouts/AppLayout';
import { cn } from '@/lib/cn';
import {
  detectPreset,
  formatCompact,
  formatInt,
  formatPercent,
  getUsage,
  loadMoreCalls,
  parseCompactDate,
  presetLabel,
  presetRange,
  recentCalls,
  TODAY,
  type CallStatus,
  type DateRange,
  type UsageReport,
} from '@/services/usage';

import { DateRangePicker } from './components/DateRangePicker';

const PAGE = 20;

/** 统计周期同步到 URL（?from=20260921&to=20260927），刷新 / 分享保持一致 */
function useRange(): [DateRange, (r: DateRange) => void] {
  const [params, setParams] = useSearchParams();
  const from = parseCompactDate(params.get('from') ?? '');
  const to = parseCompactDate(params.get('to') ?? '');
  const range = from && to && from <= to && to <= TODAY ? { from, to } : presetRange('7d');
  const set = (r: DateRange) => setParams({ from: r.from.replaceAll('-', ''), to: r.to.replaceAll('-', '') }, { replace: true });
  return [range, set];
}

/** E1 用量总览 / E2 选择统计周期 / E3 暂无数据 */
export default function UsagePage() {
  const toast = useToast();
  const [range, setRange] = useRange();
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [limit, setLimit] = useState(5);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await getUsage(range));
    } catch (e) {
      toast(e instanceof Error ? e.message : '用量数据加载失败', { tone: 'error' });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range.from, range.to]);

  useEffect(() => {
    setLimit(5);
    void load();
  }, [load]);

  const preset = detectPreset(range);
  const eyebrow = `用量 · ${preset === 'custom' ? '自定义周期' : presetLabel[preset]}${report?.change ? ' · 较上一周期' : ''}`;

  return (
    <PageColumn>
      <PageHeader
        eyebrow={eyebrow}
        title="Token 消耗"
        description="按模型与调用统计 LinkRag 的系统用量。"
        actions={
          <div className="flex items-center gap-2.5">
            <DateRangePicker value={range} onChange={setRange} />
            <Button
              variant="secondary"
              icon={<RefreshCw aria-hidden className={cn('size-3', loading && 'animate-spin')} />}
              disabled={loading}
              onClick={async () => {
                await load();
                toast('用量数据已刷新');
              }}
            >
              刷新
            </Button>
          </div>
        }
      />

      {/* 5 个用量接口全部返回后再整体展示；切换周期 / 刷新时同样回到整页加载，避免新旧数据混排 */}
      {!report || loading ? (
        <PageLoading />
      ) : report.empty ? (
        <Empty />
      ) : (
        <div className="flex flex-col">
          <Summary report={report} />
          <div className="mt-4 flex items-start gap-4">
            <Trend report={report} />
            <Models report={report} />
          </div>
          <SectionLabel label="最近调用" action={<span className="font-num text-muted">{formatInt(report.recentTotal)} 条</span>} className="mt-7 mb-[18px]" />
          <CallTable range={range} limit={limit} total={report.recentTotal} onMore={() => {
              const next = limit + PAGE;
              const pending = loadMoreCalls(range, next);
              // Mock 模式无需请求，直接展开；真实模式等下一页返回后再展开
              if (!pending) setLimit(next);
              else void pending.then(() => setLimit(next));
            }} />
        </div>
      )}
    </PageColumn>
  );
}

function Change({ value }: { value: number }) {
  const up = value >= 0;
  return (
    <span className={cn('flex items-center gap-0.5 text-[11.5px]', up ? 'text-green' : 'text-red')}>
      {up ? <ArrowUp aria-hidden className="size-3" /> : <ArrowDown aria-hidden className="size-3" />}
      <span className="sr-only">{up ? '上升' : '下降'}</span>
      {formatPercent(Math.abs(value))} 环比
    </span>
  );
}

function Summary({ report }: { report: UsageReport }) {
  const { totals, change } = report;
  const minor = [
    { label: '输入 Token', value: formatCompact(totals.input) },
    { label: '输出 Token', value: formatCompact(totals.output) },
    { label: '成功率', value: totals.successRate === null ? '—' : formatPercent(totals.successRate) },
    { label: '平均延迟', value: totals.avgLatency === null ? '—' : `${totals.avgLatency.toFixed(2)}s` },
  ];
  return (
    <section aria-label="用量汇总" className="flex items-end gap-10 rounded-2xl border border-line bg-white px-6 py-[22px] shadow-card">
      {[
        { label: '总 Token', value: totals.tokens, change: change?.tokens },
        { label: '调用次数', value: totals.calls, change: change?.calls },
      ].map((s) => (
        <div key={s.label} className="flex flex-col gap-2">
          <span className="text-[11px] text-muted">{s.label}</span>
          <span className="font-num text-[34px] leading-none font-semibold tracking-[-0.01em] text-ink">{formatInt(s.value)}</span>
          {s.change === undefined ? <span className="text-[11.5px] text-muted">上一周期无数据</span> : <Change value={s.change} />}
        </div>
      ))}
      <div aria-hidden className="mb-0 h-[70px] w-px bg-divider" />
      <dl className="flex gap-8">
        {minor.map((m) => (
          <div key={m.label} className="flex flex-col gap-1.5">
            <dt className="text-[11px] text-muted">{m.label}</dt>
            <dd className="font-num text-[18px] leading-[22px] font-semibold text-ink">{m.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Trend({ report }: { report: UsageReport }) {
  const max = Math.max(...report.trend.map((t) => t.tokens), 1);
  const [hover, setHover] = useState<number | null>(null);
  const peak = report.trend.reduce((best, t, i) => (t.tokens > report.trend[best].tokens ? i : best), 0);
  const shown = hover ?? peak;
  // 柱子较多时只标注部分日期，避免重叠
  const every = Math.ceil(report.trend.length / 10);
  return (
    <section aria-label="Token 趋势" className="flex min-w-0 flex-1 flex-col gap-3.5 rounded-2xl border border-line bg-white px-5 pt-[18px] pb-4 shadow-card">
      <div className="flex items-center">
        <h3 className="flex-1 text-[13px] font-medium text-ink">Token 趋势</h3>
        <span className="text-[11px] text-muted">{report.granularity === 'day' ? '每日' : '每周'}</span>
      </div>
      <div className="relative h-[170px]" onMouseLeave={() => setHover(null)}>
        {[0, 50, 100, 150].map((y) => (
          <div key={y} aria-hidden className="absolute inset-x-0 h-px bg-divider" style={{ top: y }} />
        ))}
        <ol className="absolute inset-x-0 top-0 flex h-[150px] items-end justify-around gap-1">
          {report.trend.map((t, i) => {
            const h = Math.max(t.tokens ? 3 : 0, Math.round((t.tokens / max) * 140));
            return (
              <li key={t.from} className="relative flex h-full max-w-9 min-w-0 flex-1 items-end justify-center" onMouseEnter={() => setHover(i)}>
                {i === shown && t.tokens > 0 && (
                  <span className="absolute font-num text-[10.5px] font-semibold whitespace-nowrap text-blue" style={{ bottom: h + 4 }}>
                    {formatCompact(t.tokens)}
                  </span>
                )}
                <span
                  aria-label={`${t.label}${report.granularity === 'week' ? ' 起一周' : ''}：${formatInt(t.tokens)} Token`}
                  role="img"
                  className={cn('w-full rounded-t-[3px] transition-colors', i === shown ? 'bg-blue' : 'bg-blue/25')}
                  style={{ height: h }}
                />
                <span aria-hidden className={cn('absolute top-[156px] font-num text-[10px] font-medium whitespace-nowrap text-muted', i % every && i !== shown && 'invisible')}>
                  {t.label}
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

function Models({ report }: { report: UsageReport }) {
  // 用 conic-gradient 画环形图，中心挖空
  let acc = 0;
  const stops = report.models.map((m) => {
    const s = `${m.color} ${acc * 360}deg ${(acc + m.share) * 360}deg`;
    acc += m.share;
    return s;
  });
  return (
    <section aria-label="模型用量" className="flex w-[300px] shrink-0 flex-col gap-4 rounded-2xl border border-line bg-white px-5 py-[18px] shadow-card">
      <h3 className="text-[13px] font-medium text-ink">模型用量</h3>
      <div className="flex items-center gap-[18px]">
        <div aria-hidden className="relative size-24 shrink-0 rounded-full" style={{ background: `conic-gradient(${stops.join(', ')})` }}>
          <div className="absolute inset-[18px] rounded-full bg-white" />
        </div>
        <ul className="flex flex-col gap-[9px]">
          {report.models.map((m) => (
            <li key={m.name} className="flex items-center gap-[7px] text-[11.5px] text-text2">
              <span aria-hidden className="size-[7px] rounded-full" style={{ background: m.color }} />
              {m.name}
              <span className="font-num text-[11px] font-medium text-muted">{formatPercent(m.share, 0)}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

const statusChip: Record<CallStatus, [Tone, string]> = {
  ok: ['green', '成功'],
  timeout: ['amber', '请求超时'],
  quota: ['red', '额度不足'],
};

function CallTable({ range, limit, total, onMore }: { range: DateRange; limit: number; total: number; onMore: () => void }) {
  const rows = recentCalls(range, limit);
  // 周期跨多天时显示日期，否则只显示时间
  const showDate = range.from !== range.to;
  const cols = 'grid grid-cols-[90px_minmax(0,1fr)_120px_90px_70px_90px] items-center gap-3';
  return (
    <div role="table" aria-label="最近调用" className="flex flex-col">
      <div role="row" className={cn(cols, 'border-b border-divider pb-2.5 text-[11px] text-muted')}>
        {['时间', '模型', '场景', 'Token', '延迟', '状态'].map((h, i) => (
          <span key={h} role="columnheader" className={cn(i >= 3 && 'text-right')}>
            {h}
          </span>
        ))}
      </div>
      {rows.map((c) => {
        const [tone, label] = statusChip[c.status];
        return (
          <div key={c.id} role="row" className={cn(cols, 'border-b border-divider py-[11px]')}>
            <span role="cell" className="font-num text-[11.5px] font-medium whitespace-nowrap text-muted" title={c.time}>
              {showDate ? `${c.time.slice(5, 10)} ${c.time.slice(11, 16)}` : c.time.slice(11)}
            </span>
            <span role="cell" className="truncate font-num text-[12.5px] font-medium text-ink">
              {c.model}
            </span>
            <span role="cell" className="truncate text-[11.5px] text-text2">
              {c.scene}
            </span>
            <span role="cell" className="text-right font-num text-[11.5px] font-medium text-ink">
              {formatInt(c.tokens)}
            </span>
            <span role="cell" className="text-right font-num text-[11.5px] font-medium text-muted">
              {c.latency.toFixed(2)}s
            </span>
            <span role="cell" className="flex justify-end">
              <Chip tone={tone}>{label}</Chip>
            </span>
          </div>
        );
      })}
      {rows.length < total && (
        <button type="button" onClick={onMore} className="mt-3 self-center rounded-md px-3 py-1.5 text-[12px] text-text2 hover:bg-white hover:text-ink">
          加载更多 · 已显示 {formatInt(rows.length)} / {formatInt(total)}
        </button>
      )}
    </div>
  );
}

function Empty() {
  const navigate = useNavigate();
  const toast = useToast();
  const stats = ['总 Token', '调用次数', '成功率', '平均延迟'];
  const bars = [20, 34, 26, 44, 30, 52, 40];
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-4 gap-4">
        {stats.map((s, i) => (
          <div key={s} className="flex flex-col gap-2.5 rounded-[14px] border border-line bg-white px-[18px] py-4">
            <dt className="text-[11px] text-muted">{s}</dt>
            <dd className="font-num text-[24px] leading-[29px] font-semibold text-faint">{i < 2 ? '0' : '—'}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-dashed border-dash py-14">
        <div aria-hidden className="flex h-20 w-[200px] items-end gap-[9px] px-2.5">
          {bars.map((h, i) => (
            <span key={i} className="w-[18px] rounded-[4px] bg-divider" style={{ height: h }} />
          ))}
        </div>
        <p className="mt-1.5 text-[14px] font-medium text-ink">当前周期暂无用量数据</p>
        <p className="text-[12px] text-muted">发起一次对话或解析文件后，这里会展示 Token 消耗与调用记录。</p>
        <div className="mt-1.5 flex gap-2.5">
          <Button icon={<Plus aria-hidden className="size-3" />} onClick={() => toast('对话功能将在下一阶段上线')}>
            新建对话
          </Button>
          <Button variant="secondary" icon={<Cpu aria-hidden className="size-3" />} onClick={() => navigate('/models')}>
            检查模型配置
          </Button>
        </div>
      </div>
    </div>
  );
}
