/** D6 添加平台模型（从已上架模型 / 手动填写）；编辑时复用，能力不可改、Key 留空保留 */
import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextInput } from '@/components/ui/Field';
import { Segmented } from '@/components/ui/Segmented';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/contexts/ToastContext';

import { CAPABILITIES, CAPABILITY_LABEL, createConfig, PROTOCOLS, setConfigActive, updateConfig, type Capability, type LlmConfig, type Protocol, type Provider, type ProviderModel } from './api';
import { errMsg } from './helpers';
import { ModelPicker } from './ModelPicker';
import { selectCls } from './shared';

type Mode = 'catalog' | 'manual';
interface Manual {
  providerId: string;
  modelName: string;
  displayName: string;
  capability: Capability;
  protocol: Protocol;
  apiBaseUrl: string;
}

interface Props {
  open: boolean;
  config: LlmConfig | null;
  providers: Provider[];
  models: ProviderModel[];
  onClose: () => void;
  onSaved: () => void;
}

export function PlatformModelDialog({ open, config, providers, models, onClose, onSaved }: Props) {
  const toast = useToast();
  const editing = !!config;
  const [mode, setMode] = useState<Mode>('catalog');
  const [srcProvider, setSrcProvider] = useState('');
  const [srcCap, setSrcCap] = useState<Capability>('CHAT');
  const [picked, setPicked] = useState<number | null>(null);
  const [m, setM] = useState<Manual>({ providerId: '', modelName: '', displayName: '', capability: 'CHAT', protocol: 'openai', apiBaseUrl: '' });
  const [apiKey, setApiKey] = useState('');
  const [enable, setEnable] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setErr(null);
    setApiKey('');
    setPicked(null);
    setEnable(true);
    setMode(editing ? 'manual' : 'catalog');
    setM(
      config
        ? { providerId: String(config.providerId), modelName: config.modelName, displayName: config.displayName ?? '', capability: config.capability, protocol: config.protocol, apiBaseUrl: config.apiBaseUrl }
        : { providerId: String(providers[0]?.id ?? ''), modelName: '', displayName: '', capability: 'CHAT', protocol: providers[0]?.defaultProtocol ?? 'openai', apiBaseUrl: providers[0]?.apiBaseUrl ?? '' },
    );
  }, [open, config, editing, providers]);

  const candidates = useMemo(() => models.filter((x) => x.isActive && x.capability === srcCap && (!srcProvider || String(x.providerId) === srcProvider)), [models, srcCap, srcProvider]);
  const set = <K extends keyof Manual>(k: K, v: Manual[K]) => setM((s) => ({ ...s, [k]: v }));

  async function submit() {
    setErr(null);
    if (!editing && !apiKey.trim()) return setErr('请填写平台 API Key');
    let body;
    if (mode === 'catalog') {
      if (picked === null) return setErr('请选择一个已上架模型');
      body = { sourceProviderModelId: picked, apiKey: apiKey.trim() || undefined };
    } else {
      if (!m.providerId || !m.modelName.trim() || !/^https?:\/\/\S+$/.test(m.apiBaseUrl.trim())) return setErr('请完整填写厂商、模型名与调用地址');
      body = {
        catalogMutation: { providerId: Number(m.providerId), modelName: m.modelName.trim(), displayName: m.displayName.trim() || undefined, capability: m.capability, protocol: m.protocol, apiBaseUrl: m.apiBaseUrl.trim() },
        apiKey: apiKey.trim() || undefined,
      };
    }
    setBusy(true);
    try {
      if (config) {
        await updateConfig(config.configId, body);
        toast('平台配置已保存', { tone: 'success' });
      } else {
        const res = await createConfig(body);
        const id = res?.config?.configId;
        if (id && res.config.isActive !== enable) await setConfigActive(id, enable).catch((e) => toast(errMsg(e, '启用失败'), { tone: 'error' }));
        toast('平台模型已添加', { tone: 'success' });
      }
      onSaved();
      onClose();
    } catch (e) {
      toast(errMsg(e, '保存失败'), { tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width={560}
      title={editing ? '编辑平台模型' : '添加平台模型'}
      description="平台模型对所有用户可用，费用由平台承担"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? '保存中…' : editing ? '保存' : '添加'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {!editing && (
          <Segmented block ariaLabel="添加方式" value={mode} onChange={setMode} options={[{ value: 'catalog', label: '从已上架模型添加' }, { value: 'manual', label: '手动填写' }]} />
        )}
        {mode === 'catalog' ? (
          <ModelPicker providers={providers} models={candidates} provider={srcProvider} onProvider={setSrcProvider} capability={srcCap} onCapability={setSrcCap} picked={picked} onPick={setPicked} />
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <Field label="来源厂商" required>
              {(id) => (
                <select id={id} className={selectCls} value={m.providerId} onChange={(e) => set('providerId', e.target.value)}>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.providerName}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="能力" required hint={editing ? '能力创建后不可修改' : undefined}>
              {(id) => (
                <select id={id} className={selectCls} value={m.capability} disabled={editing} onChange={(e) => set('capability', e.target.value as Capability)}>
                  {CAPABILITIES.map((c) => (
                    <option key={c} value={c}>
                      {CAPABILITY_LABEL[c]} {c}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="真实模型名" required>
              {(id) => <TextInput id={id} value={m.modelName} onChange={(e) => set('modelName', e.target.value)} />}
            </Field>
            <Field label="展示名">
              {(id) => <TextInput id={id} value={m.displayName} onChange={(e) => set('displayName', e.target.value)} />}
            </Field>
            <Field label="协议" required>
              {(id) => (
                <select id={id} className={selectCls} value={m.protocol} onChange={(e) => set('protocol', e.target.value as Protocol)}>
                  {PROTOCOLS.map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="调用地址" required>
              {(id) => <TextInput id={id} value={m.apiBaseUrl} onChange={(e) => set('apiBaseUrl', e.target.value)} />}
            </Field>
          </div>
        )}
        <Field label="平台 API Key" required={!editing} hint={editing ? `留空则保留原 Key（${config?.apiKeyMasked}）` : 'Key 仅加密存储，界面只显示掩码'}>
          {(id, d) => <TextInput id={id} aria-describedby={d} type="password" autoComplete="new-password" value={apiKey} placeholder="sk-" onChange={(e) => setApiKey(e.target.value)} />}
        </Field>
        {!editing && (
          <div className="flex items-center justify-between rounded-[10px] bg-soft px-3.5 py-3">
            <p className="text-[12.5px] font-medium text-ink">立即启用</p>
            <Switch label="立即启用" tone="green" checked={enable} onChange={setEnable} />
          </div>
        )}
        {err && (
          <p role="alert" className="text-[12px] text-red">
            {err}
          </p>
        )}
      </div>
    </Dialog>
  );
}
