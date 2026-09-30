import { cn } from '@/lib/cn';

import type { EBlock } from './blocks';
import { outline } from './editorOps';
import { MetaPanel } from './MetaPanel';

/** 右侧：大纲（H2 / H3，点击滚动）+ 分类与标签 */
export function EditorAside({ blocks, frontMatter, onFrontMatter, showOutline }: { blocks: EBlock[]; frontMatter: string | null; onFrontMatter: (fm: string | null) => void; showOutline: boolean }) {
  const items = outline(blocks);
  return (
    <aside className="sticky top-20 hidden w-[180px] shrink-0 flex-col gap-6 self-start xl:flex">
      {showOutline && (
        <nav aria-label="大纲" className="flex flex-col gap-1">
          <p className="mb-1 text-[11px] text-muted">大纲</p>
          {items.length === 0 ? (
            <p className="text-[11.5px] text-muted/80">添加标题后显示</p>
          ) : (
            items.map((it) => (
              <button
                key={it.id}
                type="button"
                onClick={() => document.getElementById(`blk-${it.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                className={cn('truncate rounded-[5px] px-1.5 py-1 text-left text-[12px] text-text2 hover:bg-soft hover:text-ink', it.level === 3 && 'pl-4 text-[11.5px] text-muted')}
              >
                {it.text}
              </button>
            ))
          )}
        </nav>
      )}
      <MetaPanel frontMatter={frontMatter} onChange={onFrontMatter} />
    </aside>
  );
}
