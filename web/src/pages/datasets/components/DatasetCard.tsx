import { Power } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { DatasetCover } from '@/components/DocIllustration';
import { Chip } from '@/components/ui/Chip';
import { cn } from '@/lib/cn';
import { fileCount } from '@/services/datasets';
import type { Dataset } from '@/types';

import type { DatasetAction } from './DatasetActions';
import { DatasetMenu } from './DatasetMenu';

interface Props {
  dataset: Dataset;
  onAction: (action: DatasetAction | 'enable', ds: Dataset) => void;
}

/** 知识库卡片（C1）；停用态整体 55% 透明度，悬停显示「重新启用」（C13） */
export function DatasetCard({ dataset, onAction }: Props) {
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const disabled = dataset.status === 'disabled';
  const openDetail = () => navigate(`/datasets/${dataset.id}`);

  return (
    <div className="group relative">
      <div
        role="link"
        tabIndex={0}
        aria-label={`打开知识库 ${dataset.name}`}
        onClick={openDetail}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          if (e.key === 'Enter') openDetail();
          if (e.key.toLowerCase() === 'e') onAction('edit', dataset);
        }}
        className={cn(
          'flex cursor-pointer flex-col rounded-2xl border bg-white px-[7px] pt-[7px] pb-4 transition-[box-shadow,border-color]',
          menuOpen ? 'border-ink shadow-[0_8px_24px_0_rgba(0,0,0,0.08)]' : 'border-line shadow-card hover:shadow-[0_8px_24px_0_rgba(0,0,0,0.06)]',
          disabled && !menuOpen && 'opacity-55',
        )}
      >
        <DatasetCover type={dataset.coverType} />
        <div className="flex flex-col gap-1.5 px-3 pt-3.5">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13.5px] font-medium text-ink">{dataset.name}</span>
            <span className="flex-1" />
            {disabled ? <Chip tone="gray">已停用</Chip> : <Chip tone="green">已启用</Chip>}
          </div>
          <p className="truncate text-[11.5px] text-text2">{dataset.description || '暂无描述'}</p>
          <div className="mt-1 flex items-center">
            <span className="text-[11px] text-muted">
              {fileCount(dataset.id)} 个文件 · {dataset.updatedAt}
            </span>
            <span className="flex-1" />
            <DatasetMenu dataset={dataset} onAction={onAction} onOpenChange={setMenuOpen} />
          </div>
        </div>
      </div>
      {disabled && (
        <button
          type="button"
          onClick={() => onAction('enable', dataset)}
          className="absolute top-[42px] left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-[7px] bg-ink py-[9px] pr-4 pl-3 text-[12px] font-medium text-white opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 focus:opacity-100"
        >
          <Power aria-hidden className="size-3" />
          重新启用
        </button>
      )}
    </div>
  );
}
