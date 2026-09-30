/** D1 厂商 · 模型能力目录（右侧工作区） */
import { Edit3, MoreHorizontal, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Menu } from '@/components/ui/Menu';
import { Switch } from '@/components/ui/Switch';

import { StateFeedback } from '../StateFeedback';
import { Card, relTime } from '../ui';
import { CAPABILITIES, CAPABILITY_LABEL, type Capability, type Provider, type ProviderModel, type SyncJob } from './api';
import { groupByModelName } from './helpers';
import { ActiveChip, CapChip, FilterChip, IconBtn, ProviderAvatar } from './shared';

type StatusFilter = 'all' | 'on' | 'off';

interface Props {
  provider: Provider;
  models: ProviderModel[];
  query: string;
  lastSync: SyncJob | null;
  syncing: boolean;
  onEdit: () => void;
  onAddModel: (presetName?: string) => void;
  onEditModel: (m: ProviderModel) => void;
  onDeleteModel: (m: ProviderModel) => void;
  onToggleModel: (m: ProviderModel, on: boolean) => void;
  onSync: () => void;
  onToggleProvider: () => void;
  onDeleteProvider: () => void;
}

export function CatalogView(p: Props) {
  const { provider, models } = p;
  const [cap, setCap] = useState<Capability | 'all'>('all');
  const [status, setStatus] = useState<StatusFilter>('all');

  const filtered = useMemo(() => {
    const q = p.query.trim().toLowerCase();
    return models.filter(
      (m) =>
        (cap === 'all' || m.capability === cap) &&
        (status === 'all' || (status === 'on') === m.isActive) &&
        (!q || m.modelName.toLowerCase().includes(q) || (m.displayName ?? '').toLowerCase().includes(q)),
    );
  }, [models, cap, status, p.query]);
  const groups = useMemo(() => groupByModelName(filtered), [filtered]);
  const capKinds = new Set(models.map((m) => m.capability)).size;
  const activeCount = models.filter((m) => m.isActive).length;
  const hasFilter = cap !== 'all' || status !== 'all';

  return (
    <section aria-label={`${provider.providerName} 模型能力`} className="-mr-3 flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto pr-3 pb-6 [scrollbar-gutter:stable]">
      <div className="flex items-center gap-3.5">
        <ProviderAvatar name={provider.providerName} iconUrl={provider.iconUrl} type={provider.providerType} size={44} />
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-serif text-[20px] font-semibold text-ink">{provider.providerName}</h2>
            <ActiveChip on={provider.isActive} />
            <Chip tone="gray" dot={false}>
              {provider.defaultProtocol}
            </Chip>
            <Chip tone="gray" dot={false}>
              priority {provider.priority}
            </Chip>
          </div>
          <p className="truncate text-[11.5px] text-muted">
            模板地址 {provider.apiBaseUrl} · 上架 {activeCount}/{models.length} · 能力维度 {capKinds}/{CAPABILITIES.length}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="secondary" icon={<Edit3 className="size-3.5" />} onClick={p.onEdit}>
            编辑
          </Button>
          <Button variant="secondary" icon={<Plus className="size-3.5" />} onClick={() => p.onAddModel()}>
            添加模型
          </Button>
          <Button variant="secondary" icon={<RefreshCw className={p.syncing ? 'size-3.5 animate-spin' : 'size-3.5'} />} onClick={p.onSync} disabled={p.syncing}>
            {p.syncing ? '同步中…' : '同步模型'}
          </Button>
          <Button variant="secondary" onClick={p.onToggleProvider}>
            {provider.isActive ? '禁用' : '启用'}
          </Button>
          <Menu
            width={150}
            trigger={({ toggle }) => (
              <IconBtn label="更多操作" onClick={toggle}>
                <MoreHorizontal className="size-3.5" />
              </IconBtn>
            )}
            items={[{ key: 'del', label: '删除厂商', danger: true, icon: <Trash2 className="size-3.5" />, onSelect: p.onDeleteProvider }]}
          />
        </div>
      </div>
      <div className="my-5 h-px bg-divider" />

      <div className="flex flex-col gap-2.5">
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
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-9 text-[11.5px] text-muted">状态</span>
          {(
            [
              ['all', '全部'],
              ['on', '已上架'],
              ['off', '已下架'],
            ] as const
          ).map(([v, l]) => (
            <FilterChip key={v} on={status === v} onClick={() => setStatus(v)}>
              {l}
            </FilterChip>
          ))}
          {hasFilter && (
            <button
              type="button"
              className="text-[11.5px] text-muted hover:text-ink"
              onClick={() => {
                setCap('all');
                setStatus('all');
              }}
            >
              清除筛选
            </button>
          )}
        </div>
      </div>

      <div className="mt-5 mb-2.5 flex items-center gap-3 text-[11px] text-muted">
        <span className="text-[13px] font-medium text-ink">模型能力目录</span>
        <span>
          {groups.length} 个模型 · {filtered.length} 个能力
        </span>
        <span className="ml-auto">最近同步 {p.lastSync ? relTime(p.lastSync.startedAt) : '—'}</span>
      </div>

      {groups.length === 0 ? (
        <Card>
          <StateFeedback
            kind="empty"
            title={models.length ? '没有符合条件的模型能力' : '该厂商还没有模型'}
            desc={models.length ? '调整筛选条件后重试' : '手动添加模型，或从 models.dev 同步候选后发布'}
            action={
              !models.length && (
                <Button variant="secondary" icon={<Plus className="size-3.5" />} onClick={() => p.onAddModel()}>
                  添加模型
                </Button>
              )
            }
          />
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {groups.map((g) => (
            <Card key={g.modelName}>
              <div className="flex items-center gap-2 px-4 py-3">
                <span className="font-num text-[13px] font-medium text-ink">{g.modelName}</span>
                <Chip tone="gray" dot={false}>
                  {g.items.length} 个能力
                </Chip>
                <Chip tone={g.items.some((m) => m.isActive) ? 'green' : 'gray'} dot={false}>
                  {g.items.filter((m) => m.isActive).length}/{g.items.length} 已上架
                </Chip>
                <span className="ml-auto" />
                <IconBtn label={`为 ${g.modelName} 添加能力`} onClick={() => p.onAddModel(g.modelName)}>
                  <Plus className="size-3.5" />
                </IconBtn>
              </div>
              {g.items.map((m) => (
                <div key={m.id} className="flex items-center gap-3 border-t border-divider px-4 py-2.5">
                  <CapChip cap={m.capability} />
                  {m.displayName && <span className="text-[12px] text-ink">{m.displayName}</span>}
                  <span className="text-[11.5px] text-muted">{m.protocol}</span>
                  <span className="min-w-0 flex-1 truncate font-num text-[11.5px] text-muted">{m.apiBaseUrl}</span>
                  <Switch label={`${m.modelName} ${CAPABILITY_LABEL[m.capability]} 上架`} tone="green" checked={m.isActive} onChange={(v) => p.onToggleModel(m, v)} />
                  <IconBtn label="编辑" onClick={() => p.onEditModel(m)}>
                    <Edit3 className="size-3.5" />
                  </IconBtn>
                  <IconBtn label="删除" danger onClick={() => p.onDeleteModel(m)}>
                    <Trash2 className="size-3.5" />
                  </IconBtn>
                </div>
              ))}
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
