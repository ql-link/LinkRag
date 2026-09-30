/** D5 添加 / 编辑模型能力 */
import { Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextInput } from '@/components/ui/Field';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/contexts/ToastContext';

import {
  CAPABILITIES,
  CAPABILITY_LABEL,
  createProviderModel,
  deleteProviderModel,
  PROTOCOLS,
  setProviderModelActive,
  updateProviderModel,
  type Capability,
  type Protocol,
  type Provider,
  type ProviderModel,
} from './api';
import { errMsg } from './helpers';
import { ProviderAvatar, selectCls } from './shared';

interface Props {
  open: boolean;
  provider: Provider;
  model: ProviderModel | null;
  /** 在已有模型名下新增能力时预填 */
  presetName?: string;
  onClose: () => void;
  onSaved: () => void;
}

export function CapabilityDialog({ open, provider, model, presetName, onClose, onSaved }: Props) {
  const toast = useToast();
  const [modelName, setModelName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [capability, setCapability] = useState<Capability>('CHAT');
  const [protocol, setProtocol] = useState<Protocol>('openai');
  const [apiBaseUrl, setApiBaseUrl] = useState('');
  const [active, setActive] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);

  useEffect(() => {
    if (!open) return;
    setErrors({});
    setConfirmDel(false);
    setModelName(model?.modelName ?? presetName ?? '');
    setDisplayName(model?.displayName ?? '');
    setCapability(model?.capability ?? 'CHAT');
    setProtocol(model?.protocol ?? provider.defaultProtocol);
    setApiBaseUrl(model?.apiBaseUrl ?? provider.apiBaseUrl);
    setActive(model?.isActive ?? false);
  }, [open, model, presetName, provider]);

  async function submit() {
    const e: Record<string, string> = {};
    if (!modelName.trim()) e.modelName = '请填写真实模型名';
    if (!/^https?:\/\/\S+$/.test(apiBaseUrl.trim())) e.apiBaseUrl = '请填写以 http(s):// 开头的地址';
    setErrors(e);
    if (Object.keys(e).length) return;
    const body = { modelName: modelName.trim(), displayName: displayName.trim() || null, capability, protocol, apiBaseUrl: apiBaseUrl.trim() };
    setBusy(true);
    try {
      const saved = model ? await updateProviderModel(model.id, body) : await createProviderModel(provider.id, body);
      const id = saved?.id ?? model?.id;
      if (id && active !== (model?.isActive ?? false)) await setProviderModelActive(id, active);
      toast(model ? '模型能力已保存' : '模型能力已添加', { tone: 'success' });
      onSaved();
      onClose();
    } catch (err) {
      toast(errMsg(err, '保存失败'), { tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!model) return;
    setBusy(true);
    try {
      await deleteProviderModel(model.id);
      toast('模型能力已删除', { tone: 'success' });
      onSaved();
      onClose();
    } catch (err) {
      toast(errMsg(err, '删除失败'), { tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width={520}
      title={model ? '编辑模型能力' : '添加模型能力'}
      description={model ? `${model.modelName} · ${CAPABILITY_LABEL[model.capability]}` : `添加到 ${provider.providerName}`}
      footer={
        <>
          {model &&
            (confirmDel ? (
              <Button variant="danger" className="mr-auto" onClick={remove} disabled={busy}>
                确认删除
              </Button>
            ) : (
              <Button variant="ghost" className="mr-auto text-red" icon={<Trash2 className="size-3.5" />} onClick={() => setConfirmDel(true)}>
                删除
              </Button>
            ))}
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? '保存中…' : model ? '保存' : '添加'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-[7px]">
          <p className="text-[12px] font-medium text-ink">厂商</p>
          <div className="flex items-center gap-2 rounded-[9px] bg-soft px-3 py-2 text-[13px] text-ink">
            <ProviderAvatar name={provider.providerName} iconUrl={provider.iconUrl} type={provider.providerType} size={20} />
            {provider.providerName}
            {model && <span className="ml-auto text-[11.5px] text-muted">编辑时不可修改厂商</span>}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Field label="真实模型名" required error={errors.modelName}>
            {(id, d) => <TextInput id={id} aria-describedby={d} value={modelName} placeholder="gpt-4o-mini" invalid={!!errors.modelName} onChange={(ev) => setModelName(ev.target.value)} />}
          </Field>
          <Field label="展示名">
            {(id) => <TextInput id={id} value={displayName} placeholder="GPT-4o mini" onChange={(ev) => setDisplayName(ev.target.value)} />}
          </Field>
          <Field label="能力" required>
            {(id) => (
              <select id={id} className={selectCls} value={capability} onChange={(ev) => setCapability(ev.target.value as Capability)}>
                {CAPABILITIES.map((c) => (
                  <option key={c} value={c}>
                    {CAPABILITY_LABEL[c]} {c}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="协议" required>
            {(id) => (
              <select id={id} className={selectCls} value={protocol} onChange={(ev) => setProtocol(ev.target.value as Protocol)}>
                {PROTOCOLS.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            )}
          </Field>
        </div>
        <Field label="调用地址" required error={errors.apiBaseUrl}>
          {(id, d) => <TextInput id={id} aria-describedby={d} value={apiBaseUrl} invalid={!!errors.apiBaseUrl} onChange={(ev) => setApiBaseUrl(ev.target.value)} />}
        </Field>
        <div className="flex items-center justify-between rounded-[10px] bg-soft px-3.5 py-3">
          <div className="flex flex-col gap-1">
            <p className="text-[12.5px] font-medium text-ink">上架状态：{active ? '已上架' : '已下架'}</p>
            <p className="text-[11.5px] text-muted">下架后用户不可在模型配置中选择该模型</p>
          </div>
          <Switch label="上架" tone="green" checked={active} onChange={setActive} />
        </div>
      </div>
    </Dialog>
  );
}
