/** 筛选下拉（设计稿 E3 级别下拉）：按钮 + 选项列表，支持键盘上下选择、Enter 确认、Esc / 点击外部关闭 */
import { Check, ChevronDown } from 'lucide-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

export interface Option {
  value: string;
  label: string;
  /** 选项内的自定义展示（如级别徽标），缺省显示 label */
  render?: ReactNode;
}

interface Props {
  label: string;
  value: string;
  options: Option[];
  onChange: (v: string) => void;
  /** value 为空时显示的占位文字 */
  placeholder?: string;
  icon?: ReactNode;
  /** 按钮内文字使用数字字体（服务名、时间范围） */
  num?: boolean;
  width?: number;
  className?: string;
}

export function FilterSelect({ label, value, options, onChange, placeholder, icon, num, width = 170, className }: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const id = useId();
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', onDown);
    listRef.current?.focus();
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const show = () => {
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  };
  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    btnRef.current?.focus();
  };

  return (
    <div ref={ref} className={cn('relative flex flex-col gap-[5px]', className)}>
      <span id={`${id}-l`} className="text-[11px] text-muted">
        {label}
      </span>
      <button
        ref={btnRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-l ${id}-v`}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            show();
          }
        }}
        className="flex h-8 w-full items-center gap-2 rounded-[7px] border border-line bg-white px-[11px] text-left transition-colors hover:border-faint focus-visible:border-ink focus-visible:outline-none"
      >
        {icon && <span className="flex shrink-0 text-muted [&>svg]:size-3.5">{icon}</span>}
        <span id={`${id}-v`} className={cn('min-w-0 flex-1 truncate', num ? 'font-num text-[11.5px] font-medium' : 'text-[12px]', current?.value ? 'text-ink' : 'text-muted')}>
          {current?.value ? current.label : (placeholder ?? current?.label)}
        </span>
        <ChevronDown aria-hidden className="size-3.5 shrink-0 text-muted" />
      </button>
      {open && (
        <ul
          ref={listRef}
          role="listbox"
          tabIndex={-1}
          aria-labelledby={`${id}-l`}
          aria-activedescendant={`${id}-o${active}`}
          style={{ width }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              setOpen(false);
              btnRef.current?.focus();
            } else if (e.key === 'ArrowDown') {
              e.preventDefault();
              setActive((i) => Math.min(options.length - 1, i + 1));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setActive((i) => Math.max(0, i - 1));
            } else if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              pick(options[active].value);
            } else if (e.key === 'Tab') setOpen(false);
          }}
          className="absolute top-full left-0 z-40 mt-1.5 flex max-h-[320px] animate-rise-in flex-col gap-0.5 overflow-y-auto rounded-[10px] border border-line bg-white p-1.5 shadow-dialog outline-none"
        >
          {options.map((o, i) => {
            const selected = o.value === value;
            return (
              <li
                key={o.value || '__all'}
                id={`${id}-o${i}`}
                role="option"
                aria-selected={selected}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(o.value)}
                className={cn('flex cursor-pointer items-center gap-2 rounded-[6px] px-2 py-1.5 text-[12px] text-text2', i === active && 'bg-soft')}
              >
                {o.render ?? <span className={cn('truncate', num && 'font-num')}>{o.label}</span>}
                {selected && <Check aria-hidden className="ml-auto size-3.5 shrink-0 text-ink" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
