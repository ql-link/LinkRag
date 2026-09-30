import { Chip } from '@/components/ui/Chip';
import { cn } from '@/lib/cn';

import { growth, type DashboardDTO, type Metric } from '../api';
import { Card, CardHead, fmt } from '../ui';

import { TrendChart } from './TrendChart';

function MetricCell({ label, value, m, sub }: { label: string; value: number; m?: Metric; sub: string }) {
  const g = m && growth(m);
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2 px-5 py-[18px]">
      <p className="text-[11.5px] text-muted">{label}</p>
      <div className="flex items-end gap-2.5">
        <span className="font-num text-[28px] leading-tight font-semibold text-ink">{fmt(value)}</span>
        {g && <Chip tone={g.up ? 'green' : 'red'}>{g.text}</Chip>}
      </div>
      <p className="text-[11px] text-muted">{sub}</p>
    </div>
  );
}

function Bar({ label, n, total, color }: { label: string; n: number; total: number; color: string }) {
  const pct = total ? (n / total) * 100 : 0;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center text-[12px] text-ink">
        {label}
        <span className="ml-auto font-num text-[11.5px] font-medium text-text2">
          {fmt(n)} · {pct.toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-[3px] bg-soft">
        <div className="h-full rounded-[3px]" style={{ width: `${Math.max(pct, n ? 1.5 : 0)}%`, background: color }} />
      </div>
    </div>
  );
}

/** 设计稿 B1 统计概览：四项指标 + 用户趋势 + 用户结构 */
export function StatsView({ d }: { d: DashboardDTO }) {
  const b = d.breakdown;
  const first = d.trend[0]?.date ?? '';
  const last = d.trend[d.trend.length - 1]?.date ?? '';
  return (
    <>
      <Card className="flex items-center divide-x divide-divider">
        <MetricCell label="用户总量" value={d.totalUsers} sub="包含普通用户与管理员" />
        <MetricCell label="周期新增" value={d.newUsers.current} m={d.newUsers} sub={`上一周期 ${fmt(d.newUsers.previous)}`} />
        <MetricCell label="周期活跃" value={d.activeUsers.current} m={d.activeUsers} sub={`上一周期 ${fmt(d.activeUsers.previous)}`} />
        <MetricCell label="启用用户" value={b.enabled} sub={`禁用 ${fmt(b.disabled)}`} />
      </Card>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card className="flex min-w-0 flex-col gap-[18px] px-5 py-[18px]">
          <CardHead
            title="用户趋势"
            sub={`${first} — ${last.slice(5)} · 按日`}
            extra={
              <>
                <span className="flex items-center gap-1.5 text-text2">
                  <span className="h-0.5 w-3.5 bg-ink" />
                  活跃用户
                </span>
                <span className="flex items-center gap-1.5 text-text2">
                  <span className="h-0.5 w-3.5 bg-[#a8a8a2]" />
                  新增用户
                </span>
              </>
            }
          />
          <TrendChart trend={d.trend} />
        </Card>
        <Card className="flex flex-col gap-4 px-5 py-[18px]">
          <CardHead title="用户结构" extra={<span className="font-num font-medium">{fmt(d.totalUsers)} 人</span>} />
          <Bar label="普通用户" n={b.user} total={d.totalUsers} color="#1d1d1b" />
          <Bar label="管理员" n={b.admin} total={d.totalUsers} color="#96968f" />
          <div className="h-px bg-divider" />
          <Bar label="启用账户" n={b.enabled} total={d.totalUsers} color="#3b9a5b" />
          <Bar label="禁用账户" n={b.disabled} total={d.totalUsers} color="#d0493f" />
          <div className={cn('flex flex-col gap-1 rounded-[10px] bg-soft px-3 py-2.5 text-[11px]')}>
            <p className="font-medium text-ink">统计口径</p>
            <p className="leading-[17px] text-muted">活跃用户按成功登录去重；统计时区 Asia/Shanghai。</p>
          </div>
        </Card>
      </div>
    </>
  );
}
