/** D2 外部模型候选审核 */
import { RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';

import { StateFeedback } from '../StateFeedback';
import { Card, relTime } from '../ui';
import { CAPABILITIES, CAPABILITY_LABEL, listCandidates, listProviders, listSyncJobs, reviewCandidate, runSync, type Capability, type ReviewStatus, type SyncCandidate } from './api';
import { CandidateCard, groupStatus } from './CandidateCard';
import { errMsg, groupCandidates, type CandidateGroup } from './helpers';
import { MetadataDialog } from './MetadataDialog';
import { PublishDialog } from './PublishDialog';
import { FilterChip, isSystemProvider, LoadGate, ProviderAvatar, selectCls } from './shared';
import { useLoad } from './useLoad';

const REVIEW_TABS: [ReviewStatus | 'all', string][] = [
  ['PENDING', '待审核'],
  ['PUBLISHED', '已发布'],
  ['REJECTED', '已拒绝'],
  ['all', '全部'],
];

export function CandidatesTab({ query, providerId, onProvider }: { query: string; providerId: number | null; onProvider: (id: number | null) => void }) {
  const toast = useToast();
  // 系统厂商不参与 models.dev 同步，候选页不列出
  const providersState = useLoad(() => listProviders().then((list) => list.filter((p) => !isSystemProvider(p.providerType))));
  const pid = providerId ?? providersState.data?.[0]?.id ?? null;
  const state = useLoad(async () => {
    if (pid === null) return { candidates: [] as SyncCandidate[], lastJob: null };
    const [candidates, jobs] = await Promise.all([listCandidates({ providerId: pid }), listSyncJobs({ providerId: pid }, 1, 1).catch(() => null)]);
    return { candidates, lastJob: jobs?.items[0] ?? null };
  }, [pid]);
  const [review, setReview] = useState<ReviewStatus | 'all'>('PENDING');
  const [cap, setCap] = useState<Capability | 'all'>('all');
  const [meta, setMeta] = useState<SyncCandidate | null>(null);
  const [publishing, setPublishing] = useState<CandidateGroup | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const groups = useMemo(() => groupCandidates(state.data?.candidates ?? []), [state.data]);
  const counts = useMemo(() => {
    const c: Record<ReviewStatus, number> = { PENDING: 0, PUBLISHED: 0, REJECTED: 0 };
    for (const g of groups) c[groupStatus(g.items)] += 1;
    return c;
  }, [groups]);
  const q = query.trim().toLowerCase();
  const shown = groups.filter((g) => (review === 'all' || groupStatus(g.items) === review) && (cap === 'all' || g.items.some((c) => c.capability === cap)) && (!q || g.modelName.toLowerCase().includes(q)));
  const provider = providersState.data?.find((p) => p.id === pid) ?? null;

  async function setGroupReview(g: CandidateGroup, to: 'PENDING' | 'REJECTED') {
    setBusy(g.key);
    try {
      const targets = g.items.filter((c) => c.reviewStatus !== 'PUBLISHED' && c.reviewStatus !== to);
      await Promise.all(targets.map((c) => reviewCandidate(c.id, to)));
      toast(to === 'REJECTED' ? '已拒绝' : '已恢复为待审核', { tone: 'success' });
      state.reload();
    } catch (e) {
      toast(errMsg(e), { tone: 'error' });
    } finally {
      setBusy(null);
    }
  }

  async function sync() {
    if (pid === null) return;
    setSyncing(true);
    try {
      const job = await runSync(pid);
      if (job.status === 'FAILED') toast(`同步失败：${job.errorMessage ?? '未知错误'}`, { tone: 'error' });
      else toast(`同步完成：新增 ${job.addedCount ?? 0} · 更新 ${job.updatedCount ?? 0}`, { tone: 'success' });
      state.reload();
    } catch (e) {
      toast(errMsg(e, '同步失败'), { tone: 'error' });
    } finally {
      setSyncing(false);
    }
  }

  const job = state.data?.lastJob;
  return (
    <LoadGate state={providersState} title="厂商列表">
      {(providers) =>
        providers.length === 0 ? (
          <Card>
            <StateFeedback kind="empty" title="还没有厂商" desc="先在目录中新增厂商，再从 models.dev 同步候选" />
          </Card>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              {provider && <ProviderAvatar name={provider.providerName} iconUrl={provider.iconUrl} type={provider.providerType} size={36} />}
              <select aria-label="厂商" className={cn(selectCls, 'h-9 w-48')} value={pid ?? ''} onChange={(e) => onProvider(Number(e.target.value))}>
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.providerName}
                  </option>
                ))}
              </select>
              <p className="min-w-0 flex-1 truncate text-[11.5px] text-muted">
                来源 MODELS_DEV
                {job && ` · 最近同步 ${relTime(job.startedAt)}：${job.status === 'FAILED' ? `失败（${job.errorMessage ?? '未知错误'}）` : `新增 ${job.addedCount ?? 0}，更新 ${job.updatedCount ?? 0}，过期 ${job.staleCount ?? 0}`}`}
              </p>
              <Button variant="secondary" icon={<RefreshCw className={cn('size-3.5', syncing && 'animate-spin')} />} onClick={sync} disabled={syncing || pid === null}>
                {syncing ? '同步中…' : '同步模型'}
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-9 text-[11.5px] text-muted">状态</span>
              {REVIEW_TABS.map(([v, l]) => (
                <FilterChip key={v} on={review === v} onClick={() => setReview(v)}>
                  {l}
                  {v !== 'all' && ` ${counts[v]}`}
                </FilterChip>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-9 text-[11.5px] text-muted">能力</span>
              <FilterChip on={cap === 'all'} onClick={() => setCap('all')}>
                全部
              </FilterChip>
              {CAPABILITIES.map((c) => (
                <FilterChip key={c} on={cap === c} onClick={() => setCap(c)}>
                  {CAPABILITY_LABEL[c]}
                </FilterChip>
              ))}
            </div>
            <div className="flex items-center gap-3 text-[11px] text-muted">
              <span className="text-[13px] font-medium text-ink">外部模型候选</span>
              <span>
                待审核 {counts.PENDING} · 已发布 {counts.PUBLISHED} · 已拒绝 {counts.REJECTED}
              </span>
            </div>
            <LoadGate state={state} title="候选">
              {() =>
                shown.length === 0 ? (
                  <Card>
                    <StateFeedback kind="empty" title={groups.length ? '没有符合条件的候选' : '暂无候选'} desc={groups.length ? '调整筛选条件后重试' : '点击「同步模型」从 models.dev 拉取候选'} />
                  </Card>
                ) : (
                  <div className="flex flex-col gap-3">
                    {shown.map((g) => (
                      <CandidateCard key={g.key} group={g} busy={busy === g.key} onMeta={setMeta} onPublish={() => setPublishing(g)} onReject={() => setGroupReview(g, 'REJECTED')} onRestore={() => setGroupReview(g, 'PENDING')} />
                    ))}
                  </div>
                )
              }
            </LoadGate>
            <MetadataDialog candidate={meta} onClose={() => setMeta(null)} />
            <PublishDialog group={publishing} onClose={() => setPublishing(null)} onDone={state.reload} />
          </div>
        )
      }
    </LoadGate>
  );
}
