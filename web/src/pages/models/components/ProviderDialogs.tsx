import { Check, CheckCircle2, ExternalLink, Eye, EyeOff, KeyRound, Link2, Loader2, Search, X, XCircle } from 'lucide-react';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';

import { ProviderMark } from '@/components/ProviderMark';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { capabilityLabel, catalogEntry, type CatalogEntry } from '@/mock/models';
import { providerIcon } from '@/services/backend';
import { catalogForAdd, modelStore, saveProvider, testConnection, type ConnectionResult } from '@/services/models';

/** 弹窗外壳：与 Dialog 一致的遮罩与面板，但标题区支持厂商图标 */
function Shell({ width, labelledBy, onClose, children }: { width: number; labelledBy: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    (ref.current?.querySelector<HTMLElement>('input') ?? ref.current)?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, [onClose]);
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(29,29,27,0.28)] p-6" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={labelledBy} tabIndex={-1} style={{ width }} className="flex max-h-full flex-col gap-[18px] overflow-y-auto rounded-[18px] bg-white px-7 pt-[26px] pb-[22px] shadow-dialog">
        {children}
      </div>
    </div>,
    document.body,
  );
}

function Title({ id, title, description, icon, onClose }: { id: string; title: string; description: string; icon?: React.ReactNode; onClose: () => void }) {
  return (
    <div className="flex items-center gap-3.5">
      {icon}
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h2 id={id} className="font-serif text-[20px] leading-tight font-semibold text-ink">
          {title}
        </h2>
        <p className="text-[12.5px] text-text2">{description}</p>
      </div>
      <button type="button" onClick={onClose} aria-label="关闭" className="self-start rounded-md p-0.5 text-muted hover:bg-soft hover:text-ink">
        <X className="size-4" />
      </button>
    </div>
  );
}

interface FlowProps {
  /** 直接进入第二步（更新已接入厂商的密钥） */
  editProviderId?: string;
  onClose: () => void;
}

/** D2 → D3：选择厂商 → 填写密钥、测试连接、选择启用模型 */
export function ProviderFlow({ editProviderId, onClose }: FlowProps) {
  const [step, setStep] = useState<'pick' | 'config'>(editProviderId ? 'config' : 'pick');
  const [picked, setPicked] = useState<string | undefined>(editProviderId);
  const entry = picked ? catalogEntry(picked) : undefined;
  return step === 'pick' || !entry ? (
    <PickProvider
      picked={picked}
      onPick={setPicked}
      onClose={onClose}
      onNext={() => picked && setStep('config')}
    />
  ) : (
    <ConfigureProvider entry={entry} editing={!!editProviderId} onBack={editProviderId ? undefined : () => setStep('pick')} onClose={onClose} />
  );
}

function PickProvider({ picked, onPick, onNext, onClose }: { picked?: string; onPick: (id: string) => void; onNext: () => void; onClose: () => void }) {
  const titleId = useId();
  const [q, setQ] = useState('');
  const list = catalogForAdd().filter(({ entry }) => !q.trim() || entry.name.toLowerCase().includes(q.trim().toLowerCase()) || entry.summary.includes(q.trim()));
  return (
    <Shell width={640} labelledBy={titleId} onClose={onClose}>
      <Title id={titleId} title="添加模型厂商" description="选择要接入的厂商，下一步填写 API Key。" onClose={onClose} />
      <label className="flex h-10 items-center gap-2 rounded-[9px] border border-line bg-white px-3 focus-within:border-ink">
        <Search aria-hidden className="size-[13px] text-muted" />
        <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="搜索厂商" placeholder="搜索厂商" className="min-w-0 flex-1 bg-transparent text-[13px] text-ink placeholder:text-faint" />
      </label>
      <div role="radiogroup" aria-label="模型厂商" className="grid grid-cols-3 gap-2.5">
        {list.map(({ entry, configured }) => {
          const selected = picked === entry.id;
          return (
            <button
              key={entry.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onPick(entry.id)}
              onDoubleClick={() => {
                onPick(entry.id);
                onNext();
              }}
              className={cn('flex items-center gap-2.5 rounded-xl border px-3 py-[11px] text-left transition-colors', selected ? 'border-ink bg-soft' : 'border-line bg-white hover:border-dash')}
            >
              <ProviderMark letter={entry.letter} color={entry.color} iconUrl={providerIcon(entry.id)} size={28} />
              <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
                <span className="truncate text-[12.5px] font-medium text-ink">{entry.name}</span>
                <span className="truncate text-[10.5px] text-muted">{entry.summary}</span>
              </span>
              {configured && <Check aria-label="已接入" className="size-3 shrink-0 text-green" strokeWidth={2.5} />}
            </button>
          );
        })}
        {!list.length && <p className="col-span-3 py-6 text-center text-[12px] text-muted">没有匹配的厂商，可使用「OpenAI 兼容」接入</p>}
      </div>
      <div className="flex items-center gap-2.5">
        <p className="flex-1 text-[11.5px] text-muted">没有找到？使用「OpenAI 兼容」接入任意服务</p>
        <Button variant="secondary" className="px-3.5" onClick={onClose}>
          取消
        </Button>
        <Button disabled={!picked} onClick={onNext}>
          下一步
        </Button>
      </div>
    </Shell>
  );
}

function ConfigureProvider({ entry, editing, onBack, onClose }: { entry: CatalogEntry; editing: boolean; onBack?: () => void; onClose: () => void }) {
  const toast = useToast();
  const titleId = useId();
  const keyId = useId();
  const urlId = useId();
  const existing = modelStore.state.providers.find((p) => p.id === entry.id);
  const existingModels = modelStore.state.models.filter((m) => m.providerId === entry.id);
  const [apiKey, setApiKey] = useState('');
  const [show, setShow] = useState(false);
  const [baseUrl, setBaseUrl] = useState(existing?.baseUrl ?? '');
  const [enabled, setEnabled] = useState<string[]>(() =>
    existingModels.length ? existingModels.filter((m) => m.enabled).map((m) => m.name) : entry.models.filter((m) => !m.capabilities.includes('dense')).map((m) => m.name),
  );
  const [result, setResult] = useState<ConnectionResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const keyOptional = (editing && !!existing?.maskedKey) || entry.id === 'ollama';

  const test = async () => {
    if (!apiKey.trim() && !keyOptional) return setResult({ ok: false, message: '请先填写 API Key' });
    setTesting(true);
    setResult(await testConnection(entry.id, apiKey || (entry.id === 'ollama' ? '' : 'sk-existing-key-placeholder'), baseUrl || undefined));
    setTesting(false);
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim() && !keyOptional) return setResult({ ok: false, message: '请填写 API Key' });
    if (!enabled.length) return setResult({ ok: false, message: '请至少启用一个模型' });
    setSaving(true);
    try {
      await saveProvider({ providerId: entry.id, apiKey, baseUrl: baseUrl || undefined, enabledModels: enabled });
      toast(editing ? `已更新 ${entry.name}` : `已接入 ${entry.name} · 启用 ${enabled.length} 个模型`, { tone: 'success' });
      onClose();
    } catch (err) {
      setResult({ ok: false, message: (err as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const toggle = (name: string) => setEnabled((v) => (v.includes(name) ? v.filter((n) => n !== name) : [...v, name]));

  return (
    <Shell width={520} labelledBy={titleId} onClose={onClose}>
      <form onSubmit={save} noValidate className="flex flex-col gap-[18px]">
        <Title
          id={titleId}
          title={`配置 ${entry.name}`}
          description="填写密钥后测试连接，并选择要启用的模型。"
          icon={<ProviderMark letter={entry.letter} color={entry.color} iconUrl={providerIcon(entry.id)} size={40} />}
          onClose={onClose}
        />

        <div className="flex flex-col gap-[7px]">
          <div className="flex items-center gap-1.5">
            <label htmlFor={keyId} className="text-[12px] font-medium text-ink">
              API Key{entry.id === 'ollama' && <span className="font-normal text-muted">（选填）</span>}
            </label>
            {entry.keyUrl && (
              <a href={entry.keyUrl} target="_blank" rel="noreferrer noopener" className="flex items-center gap-[3px] text-[11px] text-blue hover:underline">
                获取密钥
                <ExternalLink aria-hidden className="size-2.5" />
              </a>
            )}
          </div>
          <div className={cn('flex h-10 items-center gap-[9px] rounded-[9px] border bg-white px-3 focus-within:border-ink', result && !result.ok ? 'border-red' : 'border-line')}>
            <KeyRound aria-hidden className="size-[13px] text-muted" />
            <input
              id={keyId}
              type={show ? 'text' : 'password'}
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                setResult(null);
              }}
              placeholder={existing?.maskedKey ? `${existing.maskedKey}（留空则不修改）` : 'sk-...'}
              aria-invalid={!!result && !result.ok}
              className="min-w-0 flex-1 bg-transparent font-num text-[12.5px] font-medium text-ink placeholder:font-normal placeholder:text-faint"
            />
            <button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? '隐藏密钥' : '显示密钥'} className="text-muted hover:text-ink">
              {show ? <EyeOff className="size-[13px]" /> : <Eye className="size-[13px]" />}
            </button>
          </div>
          {result && (
            <p role={result.ok ? 'status' : 'alert'} className={cn('flex items-center gap-1.5 text-[11.5px]', result.ok ? 'text-green' : 'text-red')}>
              {result.ok ? <CheckCircle2 aria-hidden className="size-3" /> : <XCircle aria-hidden className="size-3" />}
              {result.ok ? `连接成功 · 延迟 ${result.latency}ms · 可用 ${result.modelCount} 个模型` : result.message}
            </p>
          )}
          <p className="text-[11px] text-muted">密钥仅用于调用该厂商接口，保存后只显示首尾字符。</p>
        </div>

        <div className="flex flex-col gap-[7px]">
          <label htmlFor={urlId} className="text-[12px] font-medium text-ink">
            Base URL{!entry.needsBaseUrl && '（选填）'}
          </label>
          <div className="flex h-10 items-center gap-[9px] rounded-[9px] border border-line bg-white px-3 focus-within:border-ink">
            <Link2 aria-hidden className="size-[13px] text-muted" />
            <input
              id={urlId}
              type="url"
              value={baseUrl}
              onChange={(e) => {
                setBaseUrl(e.target.value);
                setResult(null);
              }}
              placeholder={entry.defaultBaseUrl ?? 'https://your-endpoint/v1'}
              className="min-w-0 flex-1 bg-transparent font-num text-[12.5px] font-medium text-ink placeholder:font-normal placeholder:text-faint"
            />
          </div>
        </div>

        <fieldset className="flex flex-col gap-[7px]">
          <legend className="mb-[7px] text-[12px] font-medium text-ink">启用模型</legend>
          <div className="flex flex-col rounded-[10px] border border-line">
            {entry.models.map((m, i) => {
              const on = enabled.includes(m.name);
              return (
                <label key={m.name} className={cn('flex cursor-pointer items-center gap-2.5 px-3 py-[9px] hover:bg-soft/60', i > 0 && 'border-t border-divider')}>
                  <input type="checkbox" checked={on} onChange={() => toggle(m.name)} className="peer sr-only" />
                  <span aria-hidden className={cn('flex size-[15px] shrink-0 items-center justify-center rounded-[4px] border peer-focus-visible:shadow-ring', on ? 'border-ink bg-ink' : 'border-dash bg-white')}>
                    {on && <Check className="size-2.5 text-white" strokeWidth={3} />}
                  </span>
                  <span className="font-num text-[12.5px] font-medium text-ink">{m.name}</span>
                  <span className="rounded-[5px] bg-muted/10 px-[7px] py-[3px] text-[10.5px] leading-none font-medium text-muted">{m.capabilities.map((c) => capabilityLabel[c]).join(' · ')}</span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="flex items-center gap-2.5">
          <Button variant="secondary" className="px-3.5" onClick={test} disabled={testing}>
            {testing && <Loader2 aria-hidden className="size-3 animate-spin" />}
            {testing ? '测试中…' : '测试连接'}
          </Button>
          <span className="flex-1" />
          {onBack && (
            <Button variant="secondary" className="px-3.5" onClick={onBack}>
              上一步
            </Button>
          )}
          <Button type="submit" disabled={saving}>
            {saving ? '保存中…' : editing ? '保存' : '保存并启用'}
          </Button>
        </div>
      </form>
    </Shell>
  );
}
