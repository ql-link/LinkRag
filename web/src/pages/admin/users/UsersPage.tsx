import { RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { Segmented } from '@/components/ui/Segmented';
import { cn } from '@/lib/cn';

import { AdminColumn } from '../AdminLayout';
import { adminApi, type DashboardDTO } from '../api';
import { actionBtn, StaleBanner, StateFeedback } from '../StateFeedback';
import { AdminHeader, fmt, UnderlineTabs } from '../ui';

import { StatsView } from './StatsView';
import { UserListView } from './UserListView';

type Tab = 'stats' | 'list';
type Days = '7' | '30' | '90';

/** 设计稿 B1–B4 用户看板：统计概览（周期切换、加载 / 失败态）与用户列表 */
export default function UsersPage() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get('tab') === 'list' ? 'list' : 'stats';
  const [days, setDays] = useState<Days>('30');
  const [dash, setDash] = useState<DashboardDTO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [listTotal, setListTotal] = useState<number | null>(null);
  const [listKey, setListKey] = useState(0);

  const reload = useCallback(() => {
    setLoading(true);
    adminApi
      .dashboard(Number(days) as 7 | 30 | 90)
      .then((d) => {
        setDash(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message || '加载失败'))
      .finally(() => setLoading(false));
  }, [days]);
  useEffect(reload, [reload]);

  const total = dash?.totalUsers ?? listTotal;
  const isList = tab === 'list';

  return (
    <AdminColumn>
      <AdminHeader
        eyebrow={isList ? `用户看板 · ${total === null ? '—' : fmt(total)} 位用户` : '用户看板 · User Analytics'}
        title={isList ? '用户' : '用户统计'}
        desc={isList ? '查看账号、调整角色与启用状态。' : '统计时区 Asia/Shanghai · 活跃用户按成功登录去重。'}
        actions={
          isList ? (
            <button type="button" onClick={() => setListKey((k) => k + 1)} className={cn(actionBtn, 'flex items-center gap-1.5 font-normal')}>
              <RefreshCw aria-hidden className="size-3.5" />
              刷新
            </button>
          ) : (
            <>
              <Segmented<Days>
                ariaLabel="统计周期"
                value={days}
                onChange={setDays}
                options={[
                  { value: '7', label: '近 7 天' },
                  { value: '30', label: '近 30 天' },
                  { value: '90', label: '近 90 天' },
                ]}
              />
              <button type="button" onClick={reload} disabled={loading} className={cn(actionBtn, 'flex items-center gap-1.5 font-normal disabled:opacity-60')}>
                <RefreshCw aria-hidden className={cn('size-3.5', loading && 'animate-spin')} />
                重新加载
              </button>
            </>
          )
        }
        tabs={
          <UnderlineTabs<Tab>
            label="用户看板视图"
            value={tab}
            onChange={(t) => setParams(t === 'list' ? { tab: 'list' } : {}, { replace: true })}
            items={[
              { value: 'stats', label: '统计概览' },
              { value: 'list', label: '用户列表' },
            ]}
          />
        }
      />
      {isList ? (
        <UserListView key={listKey} onTotal={setListTotal} />
      ) : !dash ? (
        error ? (
          <StateFeedback kind="error" size="page" title="用户统计加载失败" desc={error} action={<button type="button" onClick={reload} className={actionBtn}>重新加载</button>} />
        ) : (
          <StateFeedback kind="loading" size="page" title="正在加载" desc="数据较多时可能需要几秒钟" />
        )
      ) : (
        <>
          {/* 切换周期失败：保留上一次数据（设计稿 B2） */}
          {error && <StaleBanner message={`近 ${days} 天数据加载失败：${error}`} onRetry={reload} />}
          <div className={cn('transition-opacity', loading && 'opacity-60')}>
            <StatsView d={dash} />
          </div>
        </>
      )}
    </AdminColumn>
  );
}
