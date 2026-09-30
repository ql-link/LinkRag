/** D3 LinkRag 平台模型 · 平台配置 */
import { Edit3, KeyRound, Plus, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/contexts/ToastContext';

import { StateFeedback } from '../StateFeedback';
import { Card } from '../ui';
import { CAPABILITIES, CAPABILITY_LABEL, CODE_CONFIG_IN_USE, deleteConfig, listConfigs, listProviderModels, listProviders, setConfigActive, type Capability, type LlmConfig } from './api';
import { ConfirmDialog, type ConfirmState } from './ConfirmDialog';
import { EmergencyDisableDialog } from './EmergencyDisableDialog';
import { errMsg, isCode } from './helpers';
import { PlatformModelDialog } from './PlatformModelDialog';
import { CapChip, FilterChip, IconBtn, LoadGate, ProviderAvatar } from './shared';
import { useLoad } from './useLoad';

async function load() {
  const [configs, providers, models] = await Promise.all([listConfigs(), listProviders(), listProviderModels({ isActive: true })]);
  return { configs: Array.isArray(configs) ? configs : [], providers, models };
}

export function PlatformTab({ query, addSignal }: { query: string; addSignal: number }) {
  const toast = useToast();
  const state = useLoad(load);
  const [cap, setCap] = useState<Capability | 'all'>('all');
  const [dlg, setDlg] = useState<{ open: boolean; config: LlmConfig | null }>({ open: false, config: null });
  const [emergency, setEmergency] = useState<{ config: LlmConfig; inUse: boolean } | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [lastSignal, setLastSignal] = useState(addSignal);
  if (addSignal !== lastSignal) {
    setLastSignal(addSignal);
    setDlg({ open: true, config: null });
  }

  const q = query.trim().toLowerCase();
  const configs = useMemo(() => state.data?.configs ?? [], [state.data]);
  const shown = configs.filter(
    (c) => (cap === 'all' || c.capability === cap) && (!q || [c.modelName, c.displayName, c.providerName ?? '', c.apiKeyMasked].some((s) => s.toLowerCase().includes(q))),
  );
  const caps = new Set(configs.map((c) => c.capability)).size;

  async function toggle(c: LlmConfig, on: boolean) {
    try {
      await setConfigActive(c.configId, on);
      toast(on ? '已启用' : '已停用', { tone: 'success' });
      state.reload();
    } catch (e) {
      if (!on && isCode(e, CODE_CONFIG_IN_USE)) setEmergency({ config: c, inUse: true });
      else toast(errMsg(e), { tone: 'error' });
    }
  }

  function remove(c: LlmConfig) {
    setConfirm({
      title: '删除平台配置',
      desc: `确定删除「${c.displayName || c.modelName}」？删除后不可恢复。`,
      okText: '删除',
      run: async () => {
        try {
          await deleteConfig(c.configId);
          toast('已删除', { tone: 'success' });
          state.reload();
        } catch (e) {
          if (isCode(e, CODE_CONFIG_IN_USE)) toast('该配置正在被知识库使用，无法删除；可先紧急停用', { tone: 'error' });
          else toast(errMsg(e, '删除失败'), { tone: 'error' });
        }
      },
    });
  }

  return (
    <LoadGate state={state} title="平台配置">
      {(d) => (
        <div className="flex flex-col gap-5">
          <div className="flex items-center gap-3.5">
            <ProviderAvatar name="LinkRag" system size={44} />
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <h2 className="font-serif text-[20px] font-semibold text-ink">LinkRag 平台模型</h2>
                <Chip tone="blue" dot={false}>
                  全站共享
                </Chip>
              </div>
              <p className="text-[11.5px] text-muted">
                {configs.length} 个平台配置 · 覆盖 {caps} 种能力 · 用户无需自带 Key
              </p>
            </div>
            <Button icon={<Plus className="size-3.5" />} onClick={() => setDlg({ open: true, config: null })}>
              添加平台模型
            </Button>
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
            <span className="text-[13px] font-medium text-ink">平台配置</span>
            <span>
              {configs.length} 个 · {configs.filter((c) => c.isActive).length} 个启用
            </span>
          </div>
          {shown.length === 0 ? (
            <Card>
              <StateFeedback kind="empty" title={configs.length ? '没有符合条件的平台配置' : '还没有平台模型'} desc={configs.length ? '调整筛选条件后重试' : '添加平台模型后，所有用户都可以直接使用'} />
            </Card>
          ) : (
            <Card>
              {shown.map((c, i) => (
                <div key={c.configId} className={i ? 'flex items-center gap-3 border-t border-divider px-4 py-3' : 'flex items-center gap-3 px-4 py-3'}>
                  <ProviderAvatar name={c.providerName ?? c.providerType} iconUrl={c.iconUrl} system size={28} />
                  <div className="flex w-[220px] min-w-0 flex-col">
                    <span className="truncate text-[13px] font-medium text-ink">{c.displayName || c.modelName}</span>
                    <span className="truncate font-num text-[11px] text-muted">{c.modelName}</span>
                  </div>
                  <span className="w-[110px] truncate text-[11.5px] text-muted">来源 {c.providerName ?? c.providerType}</span>
                  <CapChip cap={c.capability} />
                  <span className="text-[11.5px] text-muted">{c.protocol}</span>
                  <span className="flex min-w-0 flex-1 items-center gap-1 font-num text-[11.5px] text-muted">
                    <KeyRound aria-hidden className="size-3 shrink-0" />
                    {c.apiKeyMasked || '未配置 Key'}
                  </span>
                  <Switch label={`${c.modelName} 启用`} tone="green" checked={c.isActive} onChange={(v) => toggle(c, v)} />
                  {c.editable && (
                    <IconBtn label="编辑" onClick={() => setDlg({ open: true, config: c })}>
                      <Edit3 className="size-3.5" />
                    </IconBtn>
                  )}
                  <IconBtn label="删除" danger onClick={() => remove(c)}>
                    <Trash2 className="size-3.5" />
                  </IconBtn>
                  <Button variant="ghost" className="text-red" disabled={!c.isActive} onClick={() => setEmergency({ config: c, inUse: false })}>
                    紧急停用
                  </Button>
                </div>
              ))}
            </Card>
          )}
          <PlatformModelDialog open={dlg.open} config={dlg.config} providers={d.providers} models={d.models} onClose={() => setDlg({ open: false, config: null })} onSaved={state.reload} />
          <EmergencyDisableDialog config={emergency?.config ?? null} inUse={emergency?.inUse} onClose={() => setEmergency(null)} onDone={state.reload} />
          <ConfirmDialog state={confirm} onClose={() => setConfirm(null)} />
        </div>
      )}
    </LoadGate>
  );
}
