/** D4 新增 / 编辑厂商 */
import { Upload } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextInput } from '@/components/ui/Field';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/contexts/ToastContext';

import { createProvider, PROTOCOLS, setProviderActive, updateProvider, uploadProviderIcon, type Protocol, type Provider } from './api';
import { errMsg } from './helpers';
import { ProviderAvatar, selectCls } from './shared';

interface Form {
  providerType: string;
  providerName: string;
  apiBaseUrl: string;
  defaultProtocol: Protocol;
  priority: string;
  iconUrl: string | null;
  iconObjectKey: string | null;
  isActive: boolean;
}

const empty: Form = { providerType: '', providerName: '', apiBaseUrl: '', defaultProtocol: 'openai', priority: '50', iconUrl: null, iconObjectKey: null, isActive: false };

export function ProviderDialog({ open, provider, onClose, onSaved }: { open: boolean; provider: Provider | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState<Form>(empty);
  const [errors, setErrors] = useState<Partial<Record<keyof Form, string>>>({});
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const editing = !!provider;

  useEffect(() => {
    if (!open) return;
    setErrors({});
    setF(provider ? { ...provider, priority: String(provider.priority) } : empty);
  }, [open, provider]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((s) => ({ ...s, [k]: v }));

  async function onFile(file?: File) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) return toast('图标不能超过 5MB', { tone: 'error' });
    setUploading(true);
    try {
      const r = await uploadProviderIcon(file);
      setF((s) => ({ ...s, iconUrl: r.iconUrl, iconObjectKey: r.iconObjectKey }));
    } catch (e) {
      toast(errMsg(e, '图标上传失败'), { tone: 'error' });
    } finally {
      setUploading(false);
    }
  }

  function validate() {
    const e: typeof errors = {};
    if (!editing && !/^[a-z0-9_-]{1,32}$/i.test(f.providerType.trim())) e.providerType = '请填写 1–32 位字母、数字、- 或 _';
    if (!f.providerName.trim()) e.providerName = '请填写厂商名称';
    else if (f.providerName.trim().length > 64) e.providerName = '不超过 64 个字符';
    if (!/^https?:\/\/\S+$/.test(f.apiBaseUrl.trim())) e.apiBaseUrl = '请填写以 http(s):// 开头的地址';
    if (!/^-?\d+$/.test(f.priority.trim())) e.priority = '请填写整数';
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function submit() {
    if (!validate()) return;
    const body = {
      providerName: f.providerName.trim(),
      apiBaseUrl: f.apiBaseUrl.trim(),
      defaultProtocol: f.defaultProtocol,
      priority: Number(f.priority),
      iconUrl: f.iconUrl,
      iconObjectKey: f.iconObjectKey,
    };
    setBusy(true);
    try {
      if (provider) {
        await updateProvider(provider.id, body);
        if (f.isActive !== provider.isActive) await setProviderActive(provider.id, f.isActive);
        toast('厂商已保存', { tone: 'success' });
      } else {
        await createProvider({ ...body, providerType: f.providerType.trim() });
        toast('厂商已创建，添加启用的模型后即可启用', { tone: 'success' });
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
      width={520}
      title={editing ? '编辑厂商' : '新增厂商'}
      description="保存后可在厂商下添加模型或从 models.dev 同步"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy || uploading}>
            {busy ? '保存中…' : editing ? '保存' : '创建厂商'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <ProviderAvatar name={f.providerName || f.providerType || '?'} iconUrl={f.iconUrl} type={f.providerType} size={44} />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <p className="text-[12px] font-medium text-ink">厂商图标（可选）</p>
            <p className="text-[11.5px] text-muted">PNG / SVG，不超过 5MB，建议 128×128</p>
          </div>
          <input ref={fileRef} type="file" accept="image/png,image/svg+xml,image/jpeg,image/webp" className="hidden" onChange={(e) => onFile(e.target.files?.[0])} />
          <Button variant="secondary" icon={<Upload className="size-3.5" />} onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? '上传中…' : '上传'}
          </Button>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Field label="厂商标识" required={!editing} hint="仅新建时可填" error={errors.providerType}>
            {(id, d) => <TextInput id={id} aria-describedby={d} value={f.providerType} disabled={editing} placeholder="moonshot" invalid={!!errors.providerType} onChange={(e) => set('providerType', e.target.value)} />}
          </Field>
          <Field label="厂商名称" required error={errors.providerName}>
            {(id, d) => <TextInput id={id} aria-describedby={d} value={f.providerName} placeholder="月之暗面 Kimi" invalid={!!errors.providerName} onChange={(e) => set('providerName', e.target.value)} />}
          </Field>
        </div>
        <Field label="默认调用地址" required error={errors.apiBaseUrl}>
          {(id, d) => <TextInput id={id} aria-describedby={d} value={f.apiBaseUrl} placeholder="https://api.moonshot.cn/v1" invalid={!!errors.apiBaseUrl} onChange={(e) => set('apiBaseUrl', e.target.value)} />}
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="默认协议" required>
            {(id) => (
              <select id={id} className={selectCls} value={f.defaultProtocol} onChange={(e) => set('defaultProtocol', e.target.value as Protocol)}>
                {PROTOCOLS.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            )}
          </Field>
          <Field label="优先级" hint="越小越靠前" error={errors.priority}>
            {(id, d) => <TextInput id={id} aria-describedby={d} inputMode="numeric" value={f.priority} invalid={!!errors.priority} onChange={(e) => set('priority', e.target.value)} />}
          </Field>
        </div>
        <div className="flex items-center justify-between rounded-[10px] bg-soft px-3.5 py-3">
          <div className="flex flex-col gap-1">
            <p className="text-[12.5px] font-medium text-ink">启用该厂商</p>
            <p className="text-[11.5px] text-muted">{editing ? '启用前需至少有一个已上架的模型能力' : '新建厂商默认停用，添加模型后再启用'}</p>
          </div>
          <Switch label="启用该厂商" tone="green" checked={f.isActive} disabled={!editing} onChange={(v) => set('isActive', v)} />
        </div>
      </div>
    </Dialog>
  );
}
