import { Check } from 'lucide-react';
import { useCallback, useEffect, useId, useRef, useState } from 'react';

import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';

import { METRIC_DEFS } from './data';

/** 研究与评测页公用小组件（设计稿 L9 交互状态） */

export const ext = { target: '_blank', rel: 'noreferrer noopener' } as const;

/** 胶囊按钮尺寸：设计稿 18×11 / 16×10 / 15×9 */
export const btn = {
  lg: 'gap-2 px-[18px] py-[11px] text-[14px]',
  md: 'gap-2 px-4 py-2.5 text-[13.5px]',
};

export function SectionHead({ eyebrow, title, desc, id }: { eyebrow: string; title: string; desc?: string; id?: string }) {
  return (
    <div className="flex max-w-[760px] flex-col gap-2.5">
      <p className="text-[13px] font-medium text-[#a8733f]">{eyebrow}</p>
      <h2 id={id} className="font-serif text-[clamp(24px,3vw,32px)] leading-tight font-semibold tracking-[-0.005em] text-ink">
        {title}
      </h2>
      {desc && <p className="text-[15px] leading-[25px] text-text2">{desc}</p>}
    </div>
  );
}

/** 指标名：带 ⓘ，悬停 / 聚焦显示定义（S7 指标提示） */
export function Metric({ name, className }: { name: string; className?: string }) {
  const def = METRIC_DEFS[name];
  const id = useId();
  if (!def) return <span className={className}>{name}</span>;
  return (
    <span className={cn('group/metric relative inline-flex items-center gap-1', className)}>
      <span>{name}</span>
      <button type="button" aria-describedby={id} aria-label={`${name} 的定义`} className="text-[11px] leading-none text-muted outline-none hover:text-ink focus-visible:text-ink">
        ⓘ
      </button>
      <span
        role="tooltip"
        id={id}
        className="pointer-events-none absolute bottom-full left-0 z-20 mb-2 hidden w-[min(240px,80vw)] rounded-[10px] bg-ink px-3 py-2.5 text-left font-sans text-[12px] leading-[18px] font-normal whitespace-normal text-white shadow-toast group-focus-within/metric:block group-hover/metric:block"
      >
        <span className="mb-0.5 block font-num font-medium">{name}</span>
        {def}
      </span>
    </span>
  );
}

/** 复制到剪贴板；返回 [copy, copied]，copied 在 1.6s 后复位（S4） */
export function useCopy() {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = useCallback(
    async (text: string, message = '已复制到剪贴板') => {
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        toast('复制失败，请手动选择文本复制', { tone: 'error' });
        return;
      }
      setCopied(true);
      toast(message, { tone: 'success' });
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1600);
    },
    [toast],
  );
  return [copy, copied] as const;
}

export interface MenuOption {
  value: string;
  label: string;
  desc?: string;
}

/**
 * 下拉菜单（S2）：打开时描边变为 ink、箭头翻转；当前项暖色底 + 对勾；
 * 点击外部或 Esc 关闭，键盘上下选择。
 */
export function Dropdown({ label, value, options, onChange, footer, align = 'right', variant = 'pill' }: { label: string; value: string; options: MenuOption[]; onChange: (v: string) => void; footer?: React.ReactNode; align?: 'left' | 'right'; variant?: 'pill' | 'plain' }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const openMenu = () => {
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  };
  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    trigger.current?.focus();
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setOpen(false);
      trigger.current?.focus();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) return openMenu();
      setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length);
    } else if ((e.key === 'Enter' || e.key === ' ') && open) {
      e.preventDefault();
      pick(options[active].value);
    }
  };

  return (
    <div ref={root} className="relative" onKeyDown={onKey}>
      <button
        ref={trigger}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={`${label}：${current?.label ?? ''}`}
        onClick={() => (open ? setOpen(false) : openMenu())}
        className={
          variant === 'plain'
            ? cn('flex items-center gap-1.5 py-1 text-[13.5px] transition-colors', open ? 'text-ink' : 'text-text2 hover:text-ink')
            : cn('flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-num text-[12px] font-medium text-text2 transition-colors', open ? 'border-brand bg-white text-ink' : 'border-line bg-white hover:border-dash hover:text-ink')
        }
      >
        {variant === 'plain' && <span className="text-muted">{label}</span>}
        <span className={cn(variant === 'plain' && 'font-medium text-ink')}>{current?.label}</span>
        <span aria-hidden className={cn('text-[10px] transition-transform', open && 'rotate-180')}>
          ▾
        </span>
      </button>
      {open && (
        <div className={cn('absolute top-full z-30 mt-2 min-w-full rounded-[14px] border border-divider bg-white p-1.5 shadow-[0_12px_32px_0_rgba(28,26,20,0.12)]', align === 'right' ? 'right-0' : 'left-0')}>
          <ul role="listbox" id={listId} aria-label={label} className="flex min-w-[200px] flex-col">
            {options.map((o, i) => {
              const selected = o.value === value;
              return (
                <li
                  key={o.value}
                  role="option"
                  aria-selected={selected}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => pick(o.value)}
                  className={cn('flex cursor-pointer items-center gap-3 rounded-[10px] px-3 py-2', selected ? 'bg-brand-soft' : i === active && 'bg-[#fbfbf9]')}
                >
                  <span className="flex flex-1 flex-col gap-0.5">
                    <span className={cn('font-num text-[13px]', selected ? 'font-medium text-ink' : 'text-text2')}>{o.label}</span>
                    {o.desc && <span className="text-[11.5px] text-muted">{o.desc}</span>}
                  </span>
                  {selected && <Check aria-hidden className="size-3.5 text-[#a8733f]" />}
                </li>
              );
            })}
          </ul>
          {footer && <div className="mt-1 border-t border-divider px-3 pt-2 pb-1 text-[12px]">{footer}</div>}
        </div>
      )}
    </div>
  );
}

/** 横向进度条：track 0–1 */
export function Bar({ value, strong, height = 12, className }: { value: number; strong?: boolean; height?: number; className?: string }) {
  return (
    <span aria-hidden style={{ height }} className={cn('block overflow-hidden rounded-[3px] bg-soft', className)}>
      <span style={{ width: `${Math.min(1, value) * 100}%` }} className={cn('block h-full rounded-[3px]', strong ? 'bg-[#b87a3a]' : 'bg-[#c9c8c0]')} />
    </span>
  );
}

/** 当前视口里最靠上的区块 id（用于子导航 / 目录高亮） */
export function useScrollSpy(ids: string[], rootId: string, offset = 140) {
  const [active, setActive] = useState(ids[0]);
  const key = ids.join('|');
  useEffect(() => {
    const root = document.getElementById(rootId);
    if (!root) return;
    const list = key.split('|');
    const on = () => {
      const top = root.getBoundingClientRect().top + offset;
      let cur = list[0];
      for (const id of list) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= top) cur = id;
      }
      // 滚到底时高亮最后一项
      if (root.scrollTop + root.clientHeight >= root.scrollHeight - 4) cur = list[list.length - 1];
      setActive(cur);
    };
    on();
    root.addEventListener('scroll', on, { passive: true });
    return () => root.removeEventListener('scroll', on);
  }, [key, rootId, offset]);
  return active;
}

/**
 * 原始结果下载：有地址时同源直接下载（不开新页）；
 * 尚未公开时渲染真正禁用的按钮并给出原因，避免可点击的占位链接。
 */
export function RawDownload({ href, filename, className, disabledTitle = '原始结果暂未公开', children }: { href?: string; filename?: string; className?: string; disabledTitle?: string; children: React.ReactNode }) {
  if (!href) {
    return (
      <button type="button" disabled title={disabledTitle} aria-label={`${disabledTitle}`} className={cn(className, 'cursor-not-allowed text-faint hover:border-line hover:bg-white')}>
        {children}
      </button>
    );
  }
  return (
    <a href={href} download={filename ?? true} className={className}>
      {children}
    </a>
  );
}
