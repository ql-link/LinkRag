import { Copy, Crosshair, MessageSquare, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Segmented } from '@/components/ui/Segmented';
import { SearchBox } from '@/components/ui/SearchBox';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import type { Chunk, ChunkKind } from '@/mock/chunks';

const kindChip: Record<ChunkKind, { label: string; cls: string }> = {
  text: { label: '文本', cls: 'bg-text2/10 text-text2' },
  table: { label: '表格', cls: 'bg-green/10 text-green' },
  image: { label: '图片', cls: 'bg-purple/10 text-purple' },
};

function ChunkCard({ chunk, selected, onSelect, onLocate }: { chunk: Chunk; selected: boolean; onSelect: () => void; onLocate: () => void }) {
  const toast = useToast();
  const chip = kindChip[chunk.kind];
  return (
    <article
      tabIndex={0}
      aria-selected={selected}
      onClick={onSelect}
      onKeyDown={(e) => e.key === 'Enter' && e.target === e.currentTarget && onSelect()}
      className={cn(
        'flex cursor-pointer flex-col gap-2 rounded-xl border bg-white px-3.5 py-[11px] transition-shadow',
        selected ? 'border-ink shadow-[0_3px_10px_0_rgba(0,0,0,0.07)]' : 'border-line shadow-[0_3px_10px_0_rgba(0,0,0,0.03)] hover:border-ink/30',
      )}
    >
      <header className="flex items-center gap-2">
        <span className="font-num text-[11.5px] font-semibold text-ink">#{chunk.index}</span>
        <span className={cn('rounded-[5px] px-[7px] py-[3px] text-[10.5px] leading-none font-medium', chip.cls)}>{chip.label}</span>
        <span className="truncate text-[10.5px] text-muted">{chunk.section}</span>
        <span className="flex-1" />
        <span className="shrink-0 text-[10.5px] text-muted">
          第 {chunk.page} 页 · {chunk.tokens} Token
        </span>
      </header>
      {chunk.kind === 'table' && chunk.table ? (
        <div className="overflow-hidden rounded-md border border-line text-[11px]">
          {chunk.table.map((row, r) => (
            <div key={r} className={cn('flex py-[5px] pl-2.5', r === 0 ? 'bg-soft font-medium text-ink' : 'border-t border-divider text-text2')}>
              {row.map((cell, c) => (
                <span key={c} className="w-[150px] shrink truncate pr-2">
                  {cell}
                </span>
              ))}
            </div>
          ))}
        </div>
      ) : chunk.kind === 'image' ? (
        <div className="flex gap-3">
          <div className="flex h-[62px] w-[92px] shrink-0 items-center justify-center rounded-md bg-soft text-[9.5px] text-muted">{chunk.imageCaption}</div>
          <div className="flex flex-col gap-1.5">
            <span className="flex items-center gap-1 text-[10.5px] text-purple">
              <Sparkles aria-hidden className="size-[11px]" />
              视觉模型生成描述 · {chunk.visionModel}
            </span>
            <p className="text-[11.5px] leading-[18px] text-text2">{chunk.text}</p>
          </div>
        </div>
      ) : (
        <p className={cn('text-[12px] leading-[19px]', selected ? 'text-ink' : 'line-clamp-2 text-text2')}>{chunk.text}</p>
      )}
      {selected && (
        <>
          <div className="flex gap-3.5 rounded-[7px] bg-soft px-2.5 py-1.5 text-[10.5px] text-muted">
            {chunk.overlap > 0 && <span>与上一块重叠 {chunk.overlap} Token</span>}
            <span>向量：已写入</span>
            <span className="font-medium">ID {chunk.id.replace(/^chk_f_\w+?_/, 'chk_')}</span>
          </div>
          <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
            <Button variant="secondary" icon={<Crosshair className="size-3" />} onClick={onLocate}>
              定位原文
            </Button>
            <Button
              variant="secondary"
              icon={<Copy className="size-3" />}
              onClick={() => {
                void navigator.clipboard?.writeText(chunk.text);
                toast('已复制分块内容', { tone: 'success' });
              }}
            >
              复制
            </Button>
            <span className="flex-1" />
            <Button variant="secondary" icon={<MessageSquare className="size-3" />} onClick={() => toast('对话功能将在下一阶段上线')}>
              在对话中引用
            </Button>
          </div>
        </>
      )}
    </article>
  );
}

interface ChunkListProps {
  chunks: Chunk[];
  page: number;
  pages: number;
  onPage: (p: number) => void;
  selectedId?: string;
  onSelect: (c: Chunk) => void;
}

/** C6 右侧分块列表：按类型筛选、搜索，默认展示当前页分块 */
export function ChunkList({ chunks, page, pages, onPage, selectedId, onSelect }: ChunkListProps) {
  const [kind, setKind] = useState<'all' | ChunkKind>('all');
  const [query, setQuery] = useState('');
  const count = (k: ChunkKind) => chunks.filter((c) => c.kind === k).length;

  const q = query.trim();
  const visible = useMemo(() => {
    const byKind = chunks.filter((c) => kind === 'all' || c.kind === kind);
    // 搜索时跨页展示；否则只看当前页
    return q ? byKind.filter((c) => c.text.includes(q) || c.section.includes(q)) : byKind.filter((c) => c.page === page);
  }, [chunks, kind, q, page]);

  return (
    <div className="flex h-full min-h-0 flex-col px-[22px] pt-3.5">
      <div className="flex items-center gap-2.5">
        <Segmented
          ariaLabel="分块类型"
          value={kind}
          onChange={setKind}
          options={[
            { value: 'all', label: '全部', count: chunks.length },
            { value: 'text', label: '文本', count: count('text') },
            { value: 'table', label: '表格', count: count('table') },
            { value: 'image', label: '图片', count: count('image') },
          ]}
        />
        <span className="flex-1" />
        <SearchBox value={query} onChange={setQuery} placeholder="搜索分块内容" className="w-[150px]" />
      </div>
      <div className="mt-3.5 flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto pb-4">
        {visible.length ? (
          visible.map((c) => <ChunkCard key={c.id} chunk={c} selected={c.id === selectedId} onSelect={() => onSelect(c)} onLocate={() => onPage(c.page)} />)
        ) : (
          <p className="py-12 text-center text-[12px] text-muted">{q ? '没有匹配的分块' : '该页没有此类型的分块'}</p>
        )}
      </div>
      <footer className="flex shrink-0 items-center gap-3 border-t border-divider py-3 text-[11px] text-muted">
        <span>
          {q ? `搜索到 ${visible.length} 个分块` : `第 ${page} 页 · ${visible.length} 个分块`}  ·  共 {chunks.length} 个
        </span>
        <span className="flex-1" />
        <button type="button" disabled={page <= 1 || !!q} onClick={() => onPage(page - 1)} className="text-[11.5px] font-medium text-ink disabled:font-normal disabled:text-muted">
          上一页
        </button>
        <button type="button" disabled={page >= pages || !!q} onClick={() => onPage(page + 1)} className="text-[11.5px] font-medium text-ink disabled:font-normal disabled:text-muted">
          下一页
        </button>
      </footer>
    </div>
  );
}
