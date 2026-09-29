import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/cn';

export interface MenuItem {
  key: string;
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  /** 在该项之前插入分隔线 */
  divider?: boolean;
  /** 右侧快捷键提示 */
  hint?: string;
  onSelect: () => void;
}

interface MenuProps {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  items: MenuItem[];
  align?: 'left' | 'right';
  width?: number;
  /**
   * 在触发按钮右侧弹出，并通过 portal 挂到 body 下，避免被滚动容器裁剪（侧栏对话行）。
   * body 设置了 CSS zoom，getBoundingClientRect 为缩放后的坐标，定位时换算回 CSS 像素。
   */
  side?: boolean;
}

/** 下拉操作菜单：点击外部 / Esc 关闭 */
export function Menu({ trigger, items, align = 'right', width = 180, side }: MenuProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>();
  const ref = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const inside = (t: EventTarget | null) => ref.current?.contains(t as Node) || popRef.current?.contains(t as Node);
    const onDown = (e: MouseEvent) => !inside(e.target) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const onScroll = (e: Event) => side && !inside(e.target) && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    document.addEventListener('scroll', onScroll, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('scroll', onScroll, true);
    };
  }, [open, side]);

  useLayoutEffect(() => {
    if (!open || !side || !ref.current) return;
    const zoom = parseFloat(getComputedStyle(document.body).zoom) || 1;
    const r = ref.current.getBoundingClientRect();
    const h = popRef.current?.offsetHeight ?? 0;
    const maxTop = window.innerHeight / zoom - h - 8;
    setPos({ top: Math.max(8, Math.min(r.top / zoom - 6, maxTop)), left: r.right / zoom + 8 });
  }, [open, side]);

  const list = (
    <div
      ref={popRef}
      role="menu"
      style={side ? { width, top: pos?.top, left: pos?.left, visibility: pos ? 'visible' : 'hidden' } : { width }}
      className={cn(
        'z-40 rounded-[10px] border border-line bg-white p-1 shadow-pop',
        side ? 'fixed animate-rise-in' : cn('absolute top-full mt-1.5', align === 'right' ? 'right-0' : 'left-0'),
      )}
    >
      {items.map((item) => (
        <div key={item.key}>
          {item.divider && <div className="mx-1 my-1 h-px bg-divider" />}
          <button
            role="menuitem"
            type="button"
            onClick={() => {
              setOpen(false);
              item.onSelect();
            }}
            className={cn(
              'flex h-8 w-full items-center gap-2 rounded-[7px] px-2.5 text-left text-[12.5px] [&>svg]:size-3.5',
              item.danger ? 'text-red hover:bg-red/5' : 'text-ink hover:bg-soft [&>svg]:text-text2',
            )}
          >
            {item.icon}
            {item.label}
            {item.hint && <span className="ml-auto font-num text-[10.5px] text-muted">{item.hint}</span>}
          </button>
        </div>
      ))}
    </div>
  );

  return (
    <div ref={ref} className="relative" onClick={(e) => e.stopPropagation()}>
      {trigger({
        open,
        toggle: () => {
          setPos(undefined);
          setOpen((v) => !v);
        },
      })}
      {open && (side ? createPortal(<div onClick={(e) => e.stopPropagation()}>{list}</div>, document.body) : list)}
    </div>
  );
}
