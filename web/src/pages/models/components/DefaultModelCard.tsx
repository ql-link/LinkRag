import { Check, ChevronDown, Info, Plus, Search, Settings } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { ProviderMark } from '@/components/ProviderMark';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { capabilityLabel } from '@/mock/models';
import { modelIcon } from '@/services/backend';
import { findModel, modelOptions, providerOf, setDefault, useModels } from '@/services/models';
import type { Capability, ModelInfo } from '@/types';

interface Props {
  cap: Capability;
  onAddProvider: () => void;
  onManage: () => void;
}

/** D1 默认模型卡片 + D4 切换下拉（悬停模型时预览）；向量模型只影响之后新建的知识库 */
export function DefaultModelCard({ cap, onAddProvider, onManage }: Props) {
  const toast = useToast();
  const current = useModels((s) => findModel(s.defaults[cap], s));
  const provider = useModels((s) => providerOf(current, s));
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    // 捕获阶段监听：点击页面任意其他位置（含其他卡片、弹层）都会收起
    const onDown = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const onBlur = () => setOpen(false);
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('keydown', onKey);
    window.addEventListener('blur', onBlur);
    return () => {
      document.removeEventListener('pointerdown', onDown, true);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('blur', onBlur);
    };
  }, [open]);

  const choose = async (m: ModelInfo) => {
    setOpen(false);
    if (m.id === current?.id) return;
    try {
      await setDefault(cap, m.id);
      toast(`默认${capabilityLabel[cap]}模型已切换为 ${m.name}`, { tone: 'success' });
    } catch (e) {
      toast((e as Error).message, { tone: 'error' });
    }
  };

  const body = (
    <>
      <ProviderMark letter={provider?.letter ?? '?'} color={provider?.color ?? '#96968f'} iconUrl={current ? modelIcon(current.id, provider) : provider?.iconUrl} size={32} />
      <span className="flex min-w-0 flex-col gap-1 text-left">
        <span className="text-[11px] text-muted">{capabilityLabel[cap]}</span>
        <span className="truncate text-[13px] font-medium text-ink">{current?.name ?? '未设置'}</span>
      </span>
      <span className="flex-1" />
      <ChevronDown aria-hidden className={cn('size-[13px] text-muted transition-transform', open && 'rotate-180')} />
    </>
  );

  const cardCls = 'flex w-full items-center gap-3 rounded-[14px] border bg-white p-3.5';
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`默认${capabilityLabel[cap]}模型：${current?.name ?? '未设置'}`}
        onClick={() => setOpen((v) => !v)}
        className={cn(cardCls, open ? 'border-ink shadow-ring' : 'border-line shadow-card hover:border-dash')}
      >
        {body}
      </button>
      {open && <ModelDropdown cap={cap} currentId={current?.id} onChoose={choose} onAddProvider={() => (setOpen(false), onAddProvider())} onManage={() => (setOpen(false), onManage())} />}
    </div>
  );
}

function ModelDropdown({ cap, currentId, onChoose, onAddProvider, onManage }: { cap: Capability; currentId?: string; onChoose: (m: ModelInfo) => void; onAddProvider: () => void; onManage: () => void }) {
  const opts = useModels((s) => modelOptions(cap, s));
  const providers = useModels((s) => s.providers);
  const [q, setQ] = useState('');
  // 仅在鼠标悬停或键盘移动到某个模型时预览，初始不预览
  const [hover, setHover] = useState<string | undefined>();
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => inputRef.current?.focus(), []);

  const match = (m: ModelInfo) => !q.trim() || m.name.toLowerCase().includes(q.trim().toLowerCase());
  const groups = useMemo(
    () => [
      { label: '个人', items: opts.personal.filter(match) },
      { label: '平台', items: opts.platform.filter(match) },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [opts, q],
  );
  const selectable = groups.flatMap((g) => g.items);
  const unavailable = opts.unavailable.filter((u) => match(u.model));
  const preview = selectable.find((m) => m.id === hover);
  const providerName = (m: ModelInfo, fallback?: string) => providers.find((p) => p.id === m.providerId)?.name ?? fallback ?? '';

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!selectable.length) return;
    const i = selectable.findIndex((m) => m.id === hover);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = i < 0 ? (e.key === 'ArrowDown' ? 0 : selectable.length - 1) : e.key === 'ArrowDown' ? (i + 1) % selectable.length : (i - 1 + selectable.length) % selectable.length;
      setHover(selectable[next].id);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (i >= 0) onChoose(selectable[i]);
    }
  };

  return (
    <div className="absolute top-full left-0 z-40 mt-1.5 flex items-start gap-3" onKeyDown={onKeyDown}>
      <div className="flex w-[320px] flex-col gap-0.5 rounded-xl border border-line bg-white px-1.5 pt-2 pb-1.5 shadow-[0_12px_32px_0_rgba(0,0,0,0.14)]">
        <label className="flex items-center gap-[7px] rounded-[7px] bg-soft px-2.5 py-[7px]">
          <Search aria-hidden className="size-3 text-muted" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label={`搜索${capabilityLabel[cap]}模型`}
            placeholder={`搜索${capabilityLabel[cap]}模型 · 共 ${opts.total} 个`}
            className="min-w-0 flex-1 bg-transparent text-[12px] text-ink placeholder:text-muted"
          />
        </label>
        <div role="listbox" aria-label={`${capabilityLabel[cap]}模型`} className="flex max-h-[360px] flex-col gap-0.5 overflow-y-auto">
          {groups.map(
            (g) =>
              g.items.length > 0 && (
                <div key={g.label} role="group" aria-label={g.label} className="flex flex-col gap-0.5">
                  <p className="pt-1.5 pb-1 pl-2.5 text-[10.5px] text-muted">{g.label}</p>
                  {g.items.map((m) => (
                    <button
                      key={m.id}
                      role="option"
                      type="button"
                      aria-selected={m.id === currentId}
                      onMouseEnter={() => setHover(m.id)}
                      onMouseLeave={() => setHover((h) => (h === m.id ? undefined : h))}
                      onFocus={() => setHover(m.id)}
                      onBlur={() => setHover((h) => (h === m.id ? undefined : h))}
                      onClick={() => onChoose(m)}
                      className={cn('flex w-full items-center gap-[9px] rounded-[7px] px-2.5 py-[7px] text-left', m.id === hover ? 'bg-soft' : m.id === currentId && 'bg-soft/60')}
                    >
                      <Mark model={m} />
                      <span className="truncate font-num text-[12.5px] font-medium text-ink">{m.name}</span>
                      <span className="truncate text-[11px] text-muted">{providerName(m)}</span>
                      <span className="flex-1" />
                      {m.tag && <span className="shrink-0 rounded-lg bg-soft px-1.5 py-0.5 text-[10px] leading-none font-medium text-muted">{m.tag}</span>}
                      {m.id === currentId && <Check aria-label="当前默认" className="size-3 shrink-0 text-ink" />}
                    </button>
                  ))}
                </div>
              ),
          )}
          {unavailable.length > 0 && (
            <div role="group" aria-label="不可用" className="flex flex-col gap-0.5">
              <p className="pt-1.5 pb-1 pl-2.5 text-[10.5px] text-muted">不可用</p>
              {unavailable.map(({ model, reason, providerName: fallback }) => (
                <div key={model.id} aria-disabled className="flex items-center gap-[9px] rounded-[7px] px-2.5 py-[7px] opacity-45">
                  <Mark model={model} />
                  <span className="truncate font-num text-[12.5px] font-medium text-ink">{model.name}</span>
                  <span className="truncate text-[11px] text-muted">
                    {providerName(model, fallback)} · {reason}
                  </span>
                </div>
              ))}
            </div>
          )}
          {!selectable.length && !unavailable.length && <p className="px-2.5 py-3 text-[12px] text-muted">没有匹配的模型</p>}
        </div>
        <div className="mt-0.5 h-px bg-divider" />
        <div className="flex items-center gap-1.5 px-1 pt-1 text-[12px] font-medium text-text2">
          <button type="button" onClick={onAddProvider} className="flex items-center gap-1.5 rounded-md px-1.5 py-1.5 hover:bg-soft hover:text-ink">
            <Plus aria-hidden className="size-3" />
            添加厂商
          </button>
          <span className="flex-1" />
          <button type="button" onClick={onManage} className="flex items-center gap-1.5 rounded-md px-1.5 py-1.5 hover:bg-soft hover:text-ink">
            <Settings aria-hidden className="size-3" />
            管理模型
          </button>
        </div>
      </div>

      {preview && (
        <aside aria-live="polite" className="mt-[134px] flex w-[260px] flex-col gap-2 rounded-[10px] border border-line bg-white p-3.5 text-[12px] leading-[18px] text-text2 shadow-[0_6px_18px_0_rgba(0,0,0,0.06)]">
          <p className="flex items-center gap-1.5 font-medium text-ink">
            <Info aria-hidden className="size-3 text-text2" />
            预览：{preview.name}
          </p>
          <p>{[preview.context && `上下文 ${preview.context}`, preview.supportsImage && '支持图片输入'].filter(Boolean).join(' · ') || capabilityLabel[cap]}</p>
          <p>{preview.price === undefined ? '单价以厂商为准' : preview.price === 0 ? '免费' : `单价 ¥${preview.price} / 千 Token`}</p>
          <p>{impactNote[cap]}</p>
        </aside>
      )}
    </div>
  );
}

const impactNote: Record<Capability, string> = {
  chat: '切换后新对话默认使用，进行中的对话保持原模型',
  dense: '切换后新建知识库默认使用；已创建的知识库保持绑定的向量模型，不受影响',
  sparse: '切换后新建知识库默认使用；已创建的知识库保持绑定的向量模型，不受影响',
  rerank: '切换后新的检索重排默认使用',
  vision: '切换后新的图片解析任务默认使用',
  asr: '切换后新的音视频转写任务默认使用',
};

function Mark({ model }: { model: ModelInfo }) {
  const p = useModels((s) => providerOf(model, s));
  return <ProviderMark letter={p?.letter ?? model.name.slice(0, 1).toUpperCase()} color={p?.color ?? '#1d1d1b'} iconUrl={modelIcon(model.id, p)} size={20} />;
}
