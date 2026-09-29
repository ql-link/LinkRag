import { X } from 'lucide-react';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/cn';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  /** 标题左侧图标（如停用/删除的警示图标） */
  icon?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: number;
}

/** 模态弹窗：遮罩 rgba(29,29,27,.28)，Esc / 点击遮罩关闭，打开时聚焦面板 */
export function Dialog({ open, onClose, title, description, icon, children, footer, width = 480 }: DialogProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    const first = panelRef.current?.querySelector<HTMLElement>('input, textarea, select, button[data-autofocus]');
    (first ?? panelRef.current)?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(29,29,27,0.28)] p-6" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        style={{ width }}
        className="max-h-full overflow-y-auto rounded-[18px] bg-white px-7 pt-[26px] pb-[22px] shadow-dialog outline-none"
      >
        <div className="flex items-start gap-3">
          {icon}
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <h2 id={titleId} className="font-serif text-[20px] leading-tight font-semibold text-ink">
              {title}
            </h2>
            {description && <div className="text-[12.5px] leading-[1.6] text-text2">{description}</div>}
          </div>
          <button type="button" onClick={onClose} aria-label="关闭" className="rounded-md p-0.5 text-muted hover:bg-soft hover:text-ink">
            <X className="size-4" />
          </button>
        </div>
        {children && <div className="mt-[22px]">{children}</div>}
        {footer && <div className={cn('mt-6 flex justify-end gap-2.5')}>{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
