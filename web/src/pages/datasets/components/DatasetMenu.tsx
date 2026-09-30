import { ArrowUpRight, Copy, MoreHorizontal, Pencil, Power, SlidersHorizontal, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { fileCount } from '@/services/datasets';
import type { Dataset } from '@/types';

import type { DatasetAction } from './DatasetActions';

interface Props {
  dataset: Dataset;
  onAction: (action: DatasetAction | 'enable', ds: Dataset) => void;
  onOpenChange?: (open: boolean) => void;
}

/** C10 知识库操作菜单：208px，头部展示名称与概况，危险操作置于分隔线后 */
export function DatasetMenu({ dataset, onAction, onOpenChange }: Props) {
  const [open, setOpenState] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const toast = useToast();
  const enabled = dataset.status === 'enabled';

  const setOpen = (v: boolean) => {
    setOpenState(v);
    onOpenChange?.(v);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const run = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };

  const Item = ({ icon, label, hint, danger, onClick }: { icon: React.ReactNode; label: string; hint?: string; danger?: boolean; onClick: () => void }) => (
    <button
      role="menuitem"
      type="button"
      onClick={run(onClick)}
      className={cn(
        'flex w-full items-center gap-[9px] rounded-[7px] px-2.5 py-2 text-left text-[12.5px] leading-none [&>svg]:size-[13px]',
        danger ? 'text-red hover:bg-red/5' : 'text-ink hover:bg-soft [&>svg]:text-text2',
      )}
    >
      {icon}
      <span className="flex-1">{label}</span>
      {hint && <span className="text-[10.5px] font-medium text-faint">{hint}</span>}
    </button>
  );

  return (
    <div ref={ref} className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        aria-label={`${dataset.name} 更多操作`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={cn('rounded-md p-[3px] text-muted hover:bg-soft hover:text-ink', open && 'bg-soft text-ink')}
      >
        <MoreHorizontal className="size-3.5" />
      </button>
      {open && (
        <div role="menu" className="absolute top-full right-[-3px] z-40 mt-1.5 flex w-[208px] flex-col gap-px rounded-xl border border-line bg-white p-1.5 shadow-[0_12px_32px_0_rgba(0,0,0,0.14)]">
          <div className="flex flex-col gap-[3px] px-2.5 pt-1.5 pb-2">
            <span className="truncate text-[12px] font-medium text-ink">{dataset.name}</span>
            <span className="text-[10.5px] text-muted">
              {fileCount(dataset.id)} 个文件 · {enabled ? '已启用' : '已停用'}
            </span>
          </div>
          <div className="mb-[3px] h-px bg-divider" />
          <Item icon={<ArrowUpRight />} label="打开知识库" hint="↵" onClick={() => navigate(`/datasets/${dataset.id}`)} />
          <Item icon={<Pencil />} label="编辑信息" hint="E" onClick={() => onAction('edit', dataset)} />
          <Item icon={<SlidersHorizontal />} label="解析配置" onClick={() => navigate(`/datasets/${dataset.id}/config`)} />
          <Item
            icon={<Copy />}
            label="复制知识库 ID"
            onClick={() => {
              void navigator.clipboard?.writeText(dataset.id);
              toast('已复制知识库 ID', { tone: 'success' });
            }}
          />
          <div className="my-[3px] h-px bg-divider" />
          {enabled ? (
            <Item icon={<Power />} label="停用知识库" onClick={() => onAction('disable', dataset)} />
          ) : (
            <Item icon={<Power />} label="重新启用" onClick={() => onAction('enable', dataset)} />
          )}
          <Item icon={<Trash2 />} label="删除知识库" danger onClick={() => onAction('delete', dataset)} />
        </div>
      )}
    </div>
  );
}
