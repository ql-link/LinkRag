import { Check, ChevronDown, Cpu, Database, Plus, Search, Settings } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';

import { cn } from '@/lib/cn';
import { fileCount } from '@/services/datasets';
import { modelOptions, useModels } from '@/services/models';
import { useStore } from '@/services/useStore';
import type { ModelInfo } from '@/types';

/**
 * 输入框底部胶囊 + 选择层；点击外部 / Esc 关闭。
 * 选择层通过 portal 挂到 body，避免被滚动区域裁剪：默认向上弹出，上方空间不足时改为向下，
 * 并把高度限制在可用空间内（列表区域内部滚动）。body 有 CSS zoom，坐标需换算回 CSS 像素。
 */
function Popover({
  label,
  icon,
  text,
  warn,
  width,
  plain,
  children,
}: {
  label: string;
  icon: ReactNode;
  text: string;
  /** F1 未选知识库：橙色虚线提示 */
  warn?: boolean;
  width: number;
  /** 输入框底部的纯文字触发器（复刻 LinkCV 助手的「添加资料 / 模型」行） */
  plain?: boolean;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top?: number; bottom?: number; maxHeight: number }>();
  const ref = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !ref.current) return;
    const place = () => {
      const zoom = parseFloat(getComputedStyle(document.body).zoom) || 1;
      const r = ref.current!.getBoundingClientRect();
      const vw = window.innerWidth / zoom;
      const vh = window.innerHeight / zoom;
      const [top, bottom] = [r.top / zoom, r.bottom / zoom];
      const natural = popRef.current?.scrollHeight ?? 0;
      const above = top - 8 - 12;
      const below = vh - bottom - 8 - 12;
      const left = Math.max(12, Math.min(r.left / zoom, vw - width - 12));
      if (above >= Math.min(natural, 360) || above >= below) setPos({ left, bottom: vh - top + 8, maxHeight: above });
      else setPos({ left, top: bottom + 8, maxHeight: below });
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [open, width]);

  useEffect(() => {
    if (!open) return;
    const inside = (t: EventTarget | null) => ref.current?.contains(t as Node) || popRef.current?.contains(t as Node);
    const onDown = (e: PointerEvent) => !inside(e.target) && setOpen(false);
    const onScroll = (e: Event) => !inside(e.target) && setOpen(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('scroll', onScroll, true);
    return () => {
      document.removeEventListener('pointerdown', onDown, true);
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('scroll', onScroll, true);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`${label}：${text}`}
        onClick={() => {
          setPos(undefined);
          setOpen((v) => !v);
        }}
        className={cn(
          plain
            ? cn('flex h-7 items-center gap-[5px] rounded-[7px] px-1.5 text-[12.5px] transition-colors hover:bg-soft [&>svg]:size-3.5', warn ? 'text-amber' : 'text-text2', open && 'bg-soft')
            : cn(
                'flex h-6 items-center gap-[5px] rounded-[6px] border pr-2 pl-[9px] text-[11.5px] transition-colors [&>svg]:size-3',
                warn ? 'border-dashed border-amber bg-white text-muted' : open ? 'border-ink bg-soft text-text2' : 'border-transparent bg-soft text-text2 hover:bg-active',
              ),
        )}
      >
        {icon}
        <span className="max-w-[160px] truncate">{text}</span>
        <ChevronDown aria-hidden className={cn('size-2.5! transition-transform', open && 'rotate-180')} />
      </button>
      {open &&
        createPortal(
          <div
            ref={popRef}
            role="dialog"
            aria-label={label}
            style={{ width, left: pos?.left, top: pos?.top, bottom: pos?.bottom, maxHeight: pos?.maxHeight, visibility: pos ? 'visible' : 'hidden' }}
            className={cn(
              'fixed z-50 flex animate-rise-in flex-col gap-0.5 rounded-[14px] border border-line bg-white px-1.5 py-2',
              pos?.top !== undefined ? 'shadow-pop' : 'shadow-[0_-8px_32px_0_rgba(0,0,0,0.14)]',
            )}
          >
            {children(() => setOpen(false))}
          </div>,
          document.body,
        )}
    </div>
  );
}

function SearchRow({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <label className="flex h-7 items-center gap-2 rounded-[7px] bg-soft px-2.5">
      <Search aria-hidden className="size-3 text-muted" />
      <input autoFocus value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder} className="min-w-0 flex-1 bg-transparent text-[12px] text-ink placeholder:text-muted" />
    </label>
  );
}

const Footer = ({ icon, children, onClick }: { icon: ReactNode; children: ReactNode; onClick: () => void }) => (
  <>
    <div aria-hidden className="mx-1 my-0.5 h-px bg-divider" />
    <button type="button" onClick={onClick} className="flex h-[26px] items-center gap-1.5 rounded-[7px] px-2.5 text-[12px] text-text2 hover:bg-soft [&>svg]:size-3">
      {icon}
      {children}
    </button>
  </>
);

/** F3 知识库多选：显示文件数，已停用的不可选 */
export function DatasetPicker({ value, onChange, warn, plain }: { value: string[]; onChange: (ids: string[]) => void; warn?: boolean; plain?: boolean }) {
  const navigate = useNavigate();
  const datasets = useStore((s) => s.datasets);
  const [q, setQ] = useState('');
  const selected = datasets.filter((d) => value.includes(d.id));
  const text = plain ? (selected.length ? '添加知识库' : '选择知识库') : selected.length ? `${selected[0].name}${selected.length > 1 ? ` +${selected.length - 1}` : ''}` : '选择知识库';
  const shown = datasets.filter((d) => d.name.toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <Popover label="知识库" icon={plain ? <Plus aria-hidden /> : <Database aria-hidden />} text={text} warn={warn} plain={plain} width={320}>
      {() => (
        <>
          <SearchRow value={q} onChange={setQ} placeholder="搜索知识库" />
          <p className="px-2.5 pt-2 pb-1 text-[10.5px] text-muted">可多选 · 已选 {value.length} 个</p>
          <div role="listbox" aria-multiselectable aria-label="知识库列表" className="flex max-h-[240px] min-h-0 shrink flex-col gap-0.5 overflow-y-auto">
            {shown.map((d) => {
              const on = value.includes(d.id);
              const disabled = d.status === 'disabled';
              return (
                <button
                  key={d.id}
                  type="button"
                  role="option"
                  aria-selected={on}
                  disabled={disabled}
                  onClick={() => onChange(on ? value.filter((id) => id !== d.id) : [...value, d.id])}
                  className={cn('flex h-[31px] shrink-0 items-center gap-2.5 rounded-[8px] px-2.5 text-left', on ? 'bg-soft' : 'hover:bg-soft/70', disabled && 'cursor-not-allowed opacity-60')}
                >
                  <span className={cn('flex size-[15px] items-center justify-center rounded-[4px] border', on ? 'border-ink bg-ink text-white' : 'border-dash bg-white')}>
                    {on && <Check aria-hidden className="size-2.5" strokeWidth={3} />}
                  </span>
                  <span className={cn('flex-1 truncate text-[12.5px]', on ? 'font-medium text-ink' : 'text-text2')}>{d.name}</span>
                  <span className="text-[11px] text-muted">{disabled ? '已停用' : `${fileCount(d.id)} 个文件`}</span>
                </button>
              );
            })}
            {!shown.length && <p className="px-2.5 py-3 text-[12px] text-muted">没有匹配的知识库</p>}
          </div>
          <Footer icon={<Plus aria-hidden />} onClick={() => navigate('/datasets')}>
            新建知识库
          </Footer>
        </>
      )}
    </Popover>
  );
}

/** F3b 模型选择：按「个人 / 平台」分组，显示能力标签与上下文长度 */
export function ModelPicker({ value, onChange, plain }: { value: string; onChange: (name: string) => void; plain?: boolean }) {
  const navigate = useNavigate();
  const opts = useModels((s) => modelOptions('chat', s));
  const [q, setQ] = useState('');
  const match = (m: ModelInfo) => m.name.toLowerCase().includes(q.trim().toLowerCase());
  const groups = [
    { label: '个人 · 我的密钥', items: opts.personal.filter(match) },
    { label: '平台 · 管理员提供', items: opts.platform.filter(match) },
  ].filter((g) => g.items.length);

  return (
    <Popover label="模型" icon={<Cpu aria-hidden />} text={value || '选择模型'} plain={plain} width={320}>
      {(close) => (
        <>
          <SearchRow value={q} onChange={setQ} placeholder="搜索模型" />
          <div role="listbox" aria-label="对话模型" className="flex max-h-[320px] min-h-0 shrink flex-col gap-0.5 overflow-y-auto">
            {groups.map((g) => (
              <div key={g.label} role="group" aria-label={g.label} className="flex flex-col gap-0.5">
                <p className="px-2.5 pt-2 pb-1 text-[10.5px] text-muted">{g.label}</p>
                {g.items.map((m) => {
                  const on = m.name === value;
                  return (
                    <button
                      key={m.id}
                      type="button"
                      role="option"
                      aria-selected={on}
                      onClick={() => {
                        onChange(m.name);
                        close();
                      }}
                      className={cn('flex h-[31px] shrink-0 items-center gap-2.5 rounded-[8px] px-2.5 text-left', on ? 'bg-soft' : 'hover:bg-soft/70')}
                    >
                      <span className={cn('flex size-[15px] items-center justify-center rounded-full border', on ? 'border-ink bg-ink text-white' : 'border-dash bg-white')}>
                        {on && <Check aria-hidden className="size-2.5" strokeWidth={3} />}
                      </span>
                      <span className={cn('flex-1 truncate font-num text-[12.5px]', on ? 'font-medium text-ink' : 'text-text2')}>{m.name}</span>
                      <span className="text-[11px] text-muted">{[m.tag ?? '通用', m.context].filter(Boolean).join(' · ')}</span>
                    </button>
                  );
                })}
              </div>
            ))}
            {!groups.length && <p className="px-2.5 py-3 text-[12px] text-muted">没有可用的对话模型</p>}
          </div>
          <Footer icon={<Settings aria-hidden />} onClick={() => navigate('/models')}>
            管理模型配置
          </Footer>
        </>
      )}
    </Popover>
  );
}
