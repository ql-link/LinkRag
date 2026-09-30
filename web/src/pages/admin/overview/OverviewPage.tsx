import { AlertCircle, ChevronRight, Cpu, FileText, RefreshCw, ScrollText } from 'lucide-react';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { Chip } from '@/components/ui/Chip';
import { cn } from '@/lib/cn';

import { AdminColumn } from '../AdminLayout';
import { adminApi, growth, type LogItem, type OverviewDTO, type SyncJobBrief } from '../api';
import { actionBtn, StaleBanner, StateFeedback } from '../StateFeedback';
import { AdminHeader, Card, CardHead, fmt, relTime, td, th } from '../ui';

const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

interface Data {
  overview: OverviewDTO;
  /** Loki 不可用时为 null，不影响其余区块 */
  errors: { items: LogItem[]; total: number } | null;
}

async function load(): Promise<Data> {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const [overview, errors] = await Promise.all([adminApi.overview(), adminApi.errorLogs(today, 5).catch(() => null)]);
  return { overview, errors: errors && { items: errors.items, total: errors.total } };
}

/** 设计稿 A1 管理台总览 */
export default function OverviewPage() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    setLoading(true);
    load()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message || '加载失败'))
      .finally(() => setLoading(false));
  }, []);
  useEffect(reload, [reload]);

  const now = new Date();
  const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${WEEK[now.getDay()]}`;

  return (
    <AdminColumn>
      <AdminHeader
        eyebrow={`管理台 · ${date}`}
        title="总览"
        desc="LinkRag 平台运行状态、待处理事项与最近异常。"
        actions={
          <button type="button" onClick={reload} disabled={loading} className={cn(actionBtn, 'flex items-center gap-1.5 font-normal disabled:opacity-60')}>
            <RefreshCw aria-hidden className={cn('size-3.5', loading && 'animate-spin')} />
            刷新
          </button>
        }
      />
      {!data ? (
        error ? (
          <StateFeedback kind="error" size="page" title="总览加载失败" desc={error} action={<button type="button" onClick={reload} className={actionBtn}>重新加载</button>} />
        ) : (
          <StateFeedback kind="loading" size="page" title="正在加载" desc="数据较多时可能需要几秒钟" />
        )
      ) : (
        <>
          {error && <StaleBanner message={`刷新失败：${error}`} onRetry={reload} />}
          <Content data={data} />
        </>
      )}
    </AdminColumn>
  );
}

function Stat({ label, value, sub, big, tone }: { label: string; value: ReactNode; sub?: ReactNode; big?: boolean; tone?: 'red' }) {
  return (
    <div className={cn('flex flex-col', big ? 'gap-2' : 'gap-1.5')}>
      <p className="text-[11px] text-muted">{label}</p>
      <p className={cn('font-num font-semibold', big ? 'text-[30px] leading-tight' : 'text-[18px]', tone === 'red' ? 'text-red' : 'text-ink')}>{value}</p>
      {sub}
    </div>
  );
}

function Content({ data }: { data: Data }) {
  const { overview: o, errors } = data;
  const g = growth(o.users.active7d);
  const errorCount = errors ? (errors.total >= 1000 ? '1000+' : fmt(errors.total)) : '—';
  const errorServices = errors?.items.reduce<Record<string, number>>((m, l) => ((m[l.service ?? '未知'] = (m[l.service ?? '未知'] ?? 0) + 1), m), {});
  const topService = errorServices && Object.entries(errorServices).sort((a, b) => b[1] - a[1])[0];

  return (
    <>
      <Card className="px-6 py-[22px]">
        <div className="flex flex-wrap items-end gap-10">
          <Stat label="用户总量" big value={fmt(o.users.total)} sub={<p className="text-[11.5px] text-green">↑ 本月新增 {fmt(o.users.newThisMonth)}</p>} />
          <Stat
            label="近 7 天活跃"
            big
            value={fmt(o.users.active7d.current)}
            sub={g ? <p className={cn('text-[11.5px]', g.up ? 'text-green' : 'text-red')}>{g.text} 环比</p> : <p className="text-[11.5px] text-muted">上一周期无数据</p>}
          />
          <span aria-hidden className="h-16 w-px bg-divider" />
          <div className="flex flex-wrap items-center gap-9">
            <Stat label="已上架模型" value={fmt(o.models.activeProviderModels)} />
            <Stat label="厂商" value={fmt(o.models.providers)} />
            <Stat label="平台配置" value={fmt(o.models.platformConfigs)} />
            <Stat label="已发布文章" value={fmt(o.blog.published)} />
            <Stat label="今日 ERROR" value={errorCount} tone={errors && errors.total > 0 ? 'red' : undefined} />
          </div>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-[560px_1fr]">
        <Card className="flex flex-col gap-3.5 px-5 py-[18px]">
          <Todos o={o} errors={errors} errorCount={errorCount} topService={topService} />
        </Card>
        <Card className="flex flex-col gap-3.5 px-5 py-[18px]">
          <CardHead
            title="最近同步任务"
            extra={
              <Link to="/admin/models?tab=catalog&sync=history" className="hover:text-ink">
                查看全部
              </Link>
            }
          />
          <SyncJobs jobs={o.sync?.recentJobs} />
        </Card>
      </div>

      <div className="mt-7 flex items-center text-[11px] text-muted">
        最近错误日志
        <Link to="/admin/logs?level=ERROR&range=24h" className="ml-auto hover:text-ink">
          前往日志追踪 →
        </Link>
      </div>
      <div className="mt-4">
        <ErrorLogs errors={errors} />
      </div>
    </>
  );
}

function Todos({ o, errors, errorCount, topService }: { o: OverviewDTO; errors: Data['errors']; errorCount: string; topService?: [string, number] }) {
  const lf = o.sync?.lastFailure;
  const rows: { icon: ReactNode; title: string; desc: string; value: number | string; red?: boolean; to: string }[] = [
    {
      icon: <Cpu />,
      title: '外部候选待审核',
      desc: o.sync ? 'models.dev 同步发现的新模型能力' : '模型同步表尚未迁移',
      value: o.sync ? o.sync.pendingCandidates : '—',
      to: '/admin/models?tab=candidates',
    },
    {
      icon: <AlertCircle />,
      title: '模型同步失败',
      desc: lf ? [lf.providerName ?? '未知厂商', relTime(lf.startedAt), lf.errorMessage].filter(Boolean).join(' · ') : '近 7 天没有失败任务',
      value: o.sync ? o.sync.failedJobs7d : '—',
      red: (o.sync?.failedJobs7d ?? 0) > 0,
      to: '/admin/models?tab=catalog&sync=history',
    },
    {
      icon: <FileText />,
      title: '草稿文章',
      desc: o.blog.staleDrafts > 0 ? `其中 ${o.blog.staleDrafts} 篇超过 30 天未更新` : '暂无长期未更新的草稿',
      value: o.blog.drafts,
      to: '/admin/blog?status=DRAFT',
    },
    {
      icon: <ScrollText />,
      title: '今日 ERROR 日志',
      desc: !errors ? '日志服务暂不可用' : topService ? `${topService[0]} 占最近 ${topService[1]} 条` : '今天暂无错误',
      value: errorCount,
      red: !!errors && errors.total > 0,
      to: '/admin/logs?level=ERROR&range=24h',
    },
  ];
  const open = rows.filter((r) => typeof r.value === 'number' && r.value > 0).length;
  return (
    <>
      <CardHead title="待处理" extra={`${open} 项`} />
      <ul className="flex flex-col divide-y divide-divider">
        {rows.map((r) => (
          <li key={r.title}>
            <Link to={r.to} className="group flex items-center gap-3 py-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-soft text-text2 [&>svg]:size-3.5">{r.icon}</span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="text-[12.5px] font-medium text-ink">{r.title}</span>
                <span className="truncate text-[11px] text-muted">{r.desc}</span>
              </span>
              <span className={cn('ml-auto font-num text-[15px] font-semibold', r.red ? 'text-red' : 'text-ink')}>{typeof r.value === 'number' ? fmt(r.value) : r.value}</span>
              <ChevronRight aria-hidden className="size-3.5 shrink-0 text-muted transition-transform group-hover:translate-x-0.5" />
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

const JOB_CHIP = { SUCCESS: ['green', '成功'], FAILED: ['red', '失败'], RUNNING: ['amber', '运行中'] } as const;

function SyncJobs({ jobs }: { jobs?: SyncJobBrief[] }) {
  if (!jobs) return <StateFeedback kind="empty" size="inline" title="模型同步表尚未迁移" />;
  if (!jobs.length) return <StateFeedback kind="empty" size="inline" title="还没有同步任务" />;
  return (
    <ul className="flex flex-col divide-y divide-divider">
      {jobs.map((j) => {
        const [tone, label] = JOB_CHIP[j.status] ?? ['gray', j.status];
        return (
          <li key={j.id} className="flex items-center gap-2.5 py-2.5">
            <span className="text-[12.5px] font-medium text-ink">{j.providerName ?? `厂商 #${j.providerId}`}</span>
            <Chip tone={tone}>{label}</Chip>
            <span className="ml-auto font-num text-[11px] font-medium whitespace-pre text-text2" title={j.errorMessage ?? undefined}>
              {j.status === 'SUCCESS' ? `+${j.addedCount ?? 0}  ~${j.updatedCount ?? 0}  −${j.staleCount ?? 0}` : j.status === 'RUNNING' ? '…' : '—'}
            </span>
            <span className="w-[72px] text-right font-num text-[11px] font-medium text-muted">{relTime(j.startedAt)}</span>
          </li>
        );
      })}
    </ul>
  );
}

function ErrorLogs({ errors }: { errors: Data['errors'] }) {
  if (!errors) return <StateFeedback kind="error" size="inline" title="日志服务（Loki）暂不可用" />;
  if (!errors.items.length) return <StateFeedback kind="empty" size="inline" title="今天还没有 ERROR 日志" />;
  const time = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString('zh-CN', { hour12: false });
  };
  return (
    <table className="w-full table-fixed">
      <thead className="border-b border-divider">
        <tr>
          <th className={cn(th, 'w-[120px]')}>时间</th>
          <th className={cn(th, 'w-[86px]')}>级别</th>
          <th className={cn(th, 'w-[136px]')}>服务</th>
          <th className={cn(th, 'w-[186px]')}>trace_id</th>
          <th className={th}>message</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-divider border-b border-divider">
        {errors.items.map((l, i) => (
          <tr key={`${l.time}-${i}`}>
            <td className={cn(td, 'font-num text-[11.5px] font-medium text-muted')}>{time(l.time)}</td>
            <td className={td}>
              <Chip tone={l.level === 'WARN' ? 'amber' : 'red'}>{l.level ?? 'ERROR'}</Chip>
            </td>
            <td className={cn(td, 'truncate')}>{l.service ?? '—'}</td>
            <td className={cn(td, 'truncate font-num text-[11.5px] font-medium')}>
              {l.trace_id ? (
                <Link to={`/admin/logs?trace_id=${encodeURIComponent(l.trace_id)}`} className="hover:text-ink hover:underline">
                  {l.trace_id}
                </Link>
              ) : (
                '—'
              )}
            </td>
            <td className={cn(td, 'truncate text-ink')} title={l.message ?? undefined}>
              {l.message ?? '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
