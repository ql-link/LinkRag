/** D1 左侧厂商栏：统计 + 拖动排序 + 选择 */
import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Chip } from '@/components/ui/Chip';
import { cn } from '@/lib/cn';

import type { Provider } from './api';
import { ProviderAvatar } from './shared';

interface Props {
  providers: Provider[];
  counts: Map<number, number>;
  totalModels: number;
  selected: number | null;
  onSelect: (id: number) => void;
  onAdd: () => void;
  onReorder: (ids: number[]) => void;
}

export function ProviderRail({ providers, counts, totalModels, selected, onSelect, onAdd, onReorder }: Props) {
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);

  function drop(target: number) {
    if (drag === null || drag === target) return;
    const ids = providers.map((p) => p.id).filter((id) => id !== drag);
    ids.splice(ids.indexOf(target), 0, drag);
    onReorder(ids);
  }

  const stats = [
    { n: providers.length, label: '厂商' },
    { n: providers.filter((p) => p.isActive).length, label: '启用' },
    { n: totalModels, label: '能力' },
  ];

  return (
    <aside aria-label="厂商列表" className="flex min-h-0 w-[272px] shrink-0 flex-col gap-3 border-r border-divider pr-6">
      <div className="flex items-center justify-between">
        <p className="text-[13px] font-medium text-ink">厂商</p>
        <button type="button" aria-label="新增厂商" onClick={onAdd} className="flex h-[26px] w-7 items-center justify-center rounded-[7px] border border-line bg-white text-text2 hover:bg-soft">
          <Plus className="size-3.5" />
        </button>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {stats.map((s) => (
          <div key={s.label} className="flex flex-col gap-0.5 rounded-[10px] bg-soft px-3 py-2">
            <span className="font-num text-[17px] font-semibold text-ink">{s.n}</span>
            <span className="text-[11px] text-muted">{s.label}</span>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-muted">拖动调整展示顺序</p>
      <ul className="-mr-3 flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto pr-3 pb-2">
        {providers.map((p) => {
          const on = p.id === selected;
          return (
            <li
              key={p.id}
              draggable
              onDragStart={() => setDrag(p.id)}
              onDragEnd={() => {
                setDrag(null);
                setOver(null);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(p.id);
              }}
              onDrop={() => drop(p.id)}
              className={cn('rounded-[10px]', over === p.id && drag !== p.id && 'ring-1 ring-ink/30', drag === p.id && 'opacity-50')}
            >
              <button
                type="button"
                aria-current={on || undefined}
                onClick={() => onSelect(p.id)}
                className={cn('flex h-[46px] w-full items-center gap-2.5 rounded-[10px] px-2 text-left transition-colors', on ? 'bg-soft' : 'hover:bg-soft/60')}
              >
                <span aria-hidden className="flex cursor-grab flex-col gap-[3px] text-faint">
                  {[0, 1, 2].map((i) => (
                    <span key={i} className="block h-[2px] w-[7px] rounded bg-current" />
                  ))}
                </span>
                <ProviderAvatar name={p.providerName} iconUrl={p.iconUrl} type={p.providerType} />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className={cn('truncate text-[13px]', on ? 'font-medium text-ink' : 'text-text2')}>{p.providerName}</span>
                  <span className="truncate text-[11px] text-muted">
                    {p.providerType} · {p.defaultProtocol}
                  </span>
                </span>
                {p.isActive ? <span className="font-num text-[11.5px] text-muted">{counts.get(p.id) ?? 0}</span> : <Chip tone="gray">停用</Chip>}
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
