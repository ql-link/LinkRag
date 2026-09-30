/** 目录视图：左侧厂商栏 + 右侧能力目录，承载 D4 / D5 / D8 */
import { useEffect, useMemo, useState } from 'react';

import { useToast } from '@/contexts/ToastContext';

import { Card } from '../ui';
import { StateFeedback } from '../StateFeedback';
import {
  CAPABILITY_LABEL,
  CODE_PROVIDER_NO_ACTIVE_MODEL,
  deleteProvider,
  deleteProviderModel,
  listProviderModels,
  listProviders,
  listSyncJobs,
  reorderProviders,
  runSync,
  setProviderActive,
  setProviderModelActive,
  type Provider,
  type ProviderModel,
  type SyncJob,
} from './api';
import { CapabilityDialog } from './CapabilityDialog';
import { CatalogView } from './CatalogView';
import { ConfirmDialog, type ConfirmState } from './ConfirmDialog';
import { errMsg, isCode } from './helpers';
import { ProviderDialog } from './ProviderDialog';
import { ProviderRail } from './ProviderRail';
import { isSystemProvider, LoadGate } from './shared';
import { SyncHistoryDialog } from './SyncHistoryDialog';
import { useLoad } from './useLoad';

interface Data {
  providers: Provider[];
  models: ProviderModel[];
  /** 最近的同步任务（用于展示各厂商「最近同步」） */
  jobs: SyncJob[];
}

async function load(): Promise<Data> {
  const [providers, models, jobs] = await Promise.all([
    listProviders(),
    listProviderModels(),
    listSyncJobs({}, 1, 50).catch(() => null),
  ]);
  return { providers, models, jobs: jobs?.items ?? [] };
}

interface Props {
  query: string;
  historyOpen: boolean;
  onHistory: (open: boolean) => void;
  addProviderSignal: number;
}

export function CatalogTab({ query, historyOpen, onHistory, addProviderSignal }: Props) {
  const toast = useToast();
  const state = useLoad(load);
  const { data, reload, setData } = state;
  const [selected, setSelected] = useState<number | null>(null);
  const [providerDlg, setProviderDlg] = useState<{ open: boolean; provider: Provider | null }>({ open: false, provider: null });
  const [capDlg, setCapDlg] = useState<{ open: boolean; model: ProviderModel | null; preset?: string }>({ open: false, model: null });
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    if (addProviderSignal) setProviderDlg({ open: true, provider: null });
  }, [addProviderSignal]);

  // 搜索命中厂商名时自动切到该厂商
  // LinkRag 系统厂商的模型在「LinkRag 平台模型」中维护，目录不展示
  const providers = useMemo(() => (data?.providers ?? []).filter((p) => !isSystemProvider(p.providerType)), [data]);
  const q = query.trim().toLowerCase();
  useEffect(() => {
    if (!q) return;
    const hit = providers.find((p) => p.providerName.toLowerCase().includes(q) || p.providerType.toLowerCase().includes(q));
    if (hit) setSelected(hit.id);
  }, [q, providers]);

  const current = providers.find((p) => p.id === selected) ?? providers[0] ?? null;
  const counts = useMemo(() => {
    const m = new Map<number, number>();
    for (const x of data?.models ?? []) m.set(x.providerId, (m.get(x.providerId) ?? 0) + 1);
    return m;
  }, [data]);

  const fail = (e: unknown, fb: string) => toast(errMsg(e, fb), { tone: 'error' });

  async function reorder(ids: number[]) {
    if (!data) return;
    const prev = data.providers;
    // 排序接口要求包含全部厂商：隐藏的系统厂商追加在末尾
    const all = [...ids, ...prev.filter((p) => isSystemProvider(p.providerType)).map((p) => p.id)];
    setData({ ...data, providers: all.map((id) => prev.find((p) => p.id === id)!).filter(Boolean) });
    try {
      await reorderProviders(all);
    } catch (e) {
      setData({ ...data, providers: prev });
      fail(e, '排序保存失败');
    }
  }

  async function toggleModel(m: ProviderModel, on: boolean) {
    try {
      await setProviderModelActive(m.id, on);
      toast(on ? '已上架' : '已下架', { tone: 'success' });
      reload();
    } catch (e) {
      fail(e, '操作失败');
    }
  }

  async function toggleProvider(p: Provider) {
    try {
      await setProviderActive(p.id, !p.isActive);
      toast(p.isActive ? '厂商已禁用' : '厂商已启用', { tone: 'success' });
      reload();
    } catch (e) {
      if (isCode(e, CODE_PROVIDER_NO_ACTIVE_MODEL)) toast('启用前请先上架至少一个模型能力', { tone: 'error' });
      else fail(e, '操作失败');
    }
  }

  async function sync(p: Provider) {
    setSyncing(true);
    try {
      const job = await runSync(p.id);
      if (job.status === 'FAILED') toast(`同步失败：${job.errorMessage ?? '未知错误'}`, { tone: 'error' });
      else toast(`同步完成：新增 ${job.addedCount ?? 0} · 更新 ${job.updatedCount ?? 0} · 过期 ${job.staleCount ?? 0}`, { tone: 'success' });
      reload();
    } catch (e) {
      fail(e, '同步失败');
    } finally {
      setSyncing(false);
    }
  }

  return (
    <>
      <LoadGate state={state} title="模型目录">
        {(d) =>
          providers.length === 0 ? (
            <Card>
              <StateFeedback kind="empty" title="还没有厂商" desc="新增厂商后即可添加模型，或从 models.dev 同步" />
            </Card>
          ) : (
            <div className="flex min-h-0 flex-1 gap-7">
              <ProviderRail providers={providers} counts={counts} totalModels={d.models.filter((m) => providers.some((p) => p.id === m.providerId)).length} selected={current?.id ?? null} onSelect={setSelected} onAdd={() => setProviderDlg({ open: true, provider: null })} onReorder={reorder} />
              {current && (
                <CatalogView
                  provider={current}
                  models={d.models.filter((m) => m.providerId === current.id)}
                  query={providers.some((p) => p.providerName.toLowerCase().includes(q)) ? '' : query}
                  lastSync={d.jobs.find((j) => j.providerId === current.id) ?? null}
                  syncing={syncing}
                  onEdit={() => setProviderDlg({ open: true, provider: current })}
                  onAddModel={(preset) => setCapDlg({ open: true, model: null, preset })}
                  onEditModel={(m) => setCapDlg({ open: true, model: m })}
                  onToggleModel={toggleModel}
                  onDeleteModel={(m) =>
                    setConfirm({
                      title: '删除模型能力',
                      desc: `确定删除 ${m.modelName} · ${CAPABILITY_LABEL[m.capability]}？删除后不可恢复。`,
                      okText: '删除',
                      run: () => deleteProviderModel(m.id).then(() => (toast('已删除', { tone: 'success' }), reload()), (e) => fail(e, '删除失败')),
                    })
                  }
                  onSync={() => sync(current)}
                  onToggleProvider={() => toggleProvider(current)}
                  onDeleteProvider={() =>
                    setConfirm({
                      title: '删除厂商',
                      desc: `确定删除「${current.providerName}」？其下的模型能力将一并移除。`,
                      okText: '删除厂商',
                      run: () =>
                        deleteProvider(current.id).then(
                          () => {
                            toast('厂商已删除', { tone: 'success' });
                            setSelected(null);
                            reload();
                          },
                          (e) => fail(e, '删除失败'),
                        ),
                    })
                  }
                />
              )}
            </div>
          )
        }
      </LoadGate>
      <ProviderDialog open={providerDlg.open} provider={providerDlg.provider} onClose={() => setProviderDlg({ open: false, provider: null })} onSaved={reload} />
      {current && <CapabilityDialog open={capDlg.open} provider={current} model={capDlg.model} presetName={capDlg.preset} onClose={() => setCapDlg({ open: false, model: null })} onSaved={reload} />}
      <SyncHistoryDialog open={historyOpen} onClose={() => onHistory(false)} providers={providers} />
      <ConfirmDialog state={confirm} onClose={() => setConfirm(null)} />
    </>
  );
}
