/** D8 同步任务历史 */
import { RefreshCw } from 'lucide-react';
import { useState } from 'react';

import { Chip, type Tone } from '@/components/ui/Chip';
import { Dialog } from '@/components/ui/Dialog';
import { Segmented } from '@/components/ui/Segmented';
import { cn } from '@/lib/cn';

import { actionBtn, StateFeedback } from '../StateFeedback';
import { Pagination, relTime, td, th } from '../ui';
import { listSyncJobs, type Provider, type SyncStatus } from './api';
import { duration } from './helpers';
import { LoadGate, ProviderAvatar, selectCls } from './shared';
import { useLoad } from './useLoad';

const SIZE = 10;
const STATUS: Record<SyncStatus, { label: string; tone: Tone }> = {
  RUNNING: { label: '运行中', tone: 'blue' },
  SUCCESS: { label: '成功', tone: 'green' },
  FAILED: { label: '失败', tone: 'red' },
};

export function SyncHistoryDialog({ open, onClose, providers }: { open: boolean; onClose: () => void; providers: Provider[] }) {
  return (
    <Dialog open={open} onClose={onClose} width={920} title="同步任务历史" description="models.dev 外部目录同步记录">
      {open && <Body providers={providers} />}
    </Dialog>
  );
}

function Body({ providers }: { providers: Provider[] }) {
  const [providerId, setProviderId] = useState('');
  const [status, setStatus] = useState<SyncStatus | 'all'>('all');
  const [page, setPage] = useState(1);
  const state = useLoad(() => listSyncJobs({ providerId: providerId || undefined, status: status === 'all' ? undefined : status }, page, SIZE), [providerId, status, page]);
  const byId = new Map(providers.map((p) => [p.id, p]));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <select
          aria-label="厂商"
          className={cn(selectCls, 'h-8 w-44 text-[12px]')}
          value={providerId}
          onChange={(e) => {
            setProviderId(e.target.value);
            setPage(1);
          }}
        >
          <option value="">全部厂商</option>
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.providerName}
            </option>
          ))}
        </select>
        <Segmented
          ariaLabel="状态"
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
          options={[
            { value: 'all', label: '全部' },
            { value: 'RUNNING', label: '运行中' },
            { value: 'SUCCESS', label: '成功' },
            { value: 'FAILED', label: '失败' },
          ]}
        />
        <button type="button" onClick={state.reload} disabled={state.loading} className={cn(actionBtn, 'ml-auto flex items-center gap-1.5 py-1.5 font-normal')}>
          <RefreshCw aria-hidden className={cn('size-3.5', state.loading && 'animate-spin')} />
          刷新
        </button>
      </div>
      <LoadGate state={state} title="同步记录">
        {(d) =>
          d.items.length === 0 ? (
            <StateFeedback kind="empty" title="暂无同步记录" desc="在厂商详情中点击「同步模型」即可从 models.dev 拉取候选" />
          ) : (
            <div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-divider">
                    {['厂商', '来源', '状态', '新增', '更新', '过期', '开始', '耗时', '说明'].map((h) => (
                      <th key={h} scope="col" className={cn(th, 'px-2')}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((j) => {
                    const p = byId.get(j.providerId);
                    const s = STATUS[j.status] ?? { label: j.status, tone: 'gray' as Tone };
                    const n = (v: number | null) => (j.status === 'RUNNING' ? '…' : v ?? '—');
                    return (
                      <tr key={j.id} className="border-b border-divider last:border-0">
                        <td className={cn(td, 'px-2')}>
                          <span className="flex items-center gap-2 text-ink">
                            <ProviderAvatar name={p?.providerName ?? `#${j.providerId}`} iconUrl={p?.iconUrl} type={p?.providerType} size={20} />
                            {p?.providerName ?? `厂商 #${j.providerId}`}
                          </span>
                        </td>
                        <td className={cn(td, 'px-2 font-num text-[11px]')}>{j.syncSource}</td>
                        <td className={cn(td, 'px-2')}>
                          <Chip tone={s.tone}>{s.label}</Chip>
                        </td>
                        <td className={cn(td, 'px-2 font-num')}>{n(j.addedCount)}</td>
                        <td className={cn(td, 'px-2 font-num')}>{n(j.updatedCount)}</td>
                        <td className={cn(td, 'px-2 font-num')}>{n(j.staleCount)}</td>
                        <td className={cn(td, 'px-2 font-num whitespace-nowrap')}>{relTime(j.startedAt)}</td>
                        <td className={cn(td, 'px-2 font-num')}>{duration(j.startedAt, j.finishedAt)}</td>
                        <td className={cn(td, 'max-w-[200px] truncate px-2', j.status === 'FAILED' && 'text-red')} title={j.errorMessage ?? undefined}>
                          {j.errorMessage || (j.status === 'RUNNING' ? '正在拉取模型清单' : '—')}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <Pagination page={page} pageSize={SIZE} total={d.total} onChange={setPage} />
            </div>
          )
        }
      </LoadGate>
    </div>
  );
}
