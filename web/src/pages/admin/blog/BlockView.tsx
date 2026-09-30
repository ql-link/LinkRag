import { ArrowDown, ArrowUp, GripVertical, Trash2 } from 'lucide-react';

import { Menu } from '@/components/ui/Menu';

import type { BlockCtx } from './blockCtx';
import type { EBlock } from './blocks';
import { CodeBlock } from './CodeBlock';
import { ImageBlock } from './ImageBlock';
import { TableBlock } from './TableBlock';
import { MdBlock, RenderedText } from './TextBlock';

const TYPE_LABEL: Record<EBlock['t'], string> = { p: '段落', h: '标题', list: '列表', quote: '引用', callout: '提示块', code: '代码块', table: '表格', img: '图片', hr: '分隔线', md: '段落' };

/** 单个块 + 左侧悬停手柄（上移 / 下移 / 删除） */
export function BlockView({ b, ctx, first, onMove }: { b: EBlock; ctx: BlockCtx; first: boolean; onMove: (id: string, d: -1 | 1) => void }) {
  let body;
  switch (b.t) {
    case 'md':
      body = <MdBlock b={b} ctx={ctx} first={first} />;
      break;
    case 'hr':
      body = (
        <div role="separator" className="py-3">
          <div className="h-px bg-line" />
        </div>
      );
      break;
    case 'code':
      body = <CodeBlock b={b} ctx={ctx} />;
      break;
    case 'table':
      body = <TableBlock b={b} ctx={ctx} />;
      break;
    case 'img':
      body = <ImageBlock b={b} ctx={ctx} />;
      break;
    default:
      body = <RenderedText b={b} ctx={ctx} first={first} />;
  }
  return (
    <div className="group/block relative" data-block={b.id} id={`blk-${b.id}`}>
      <div className="absolute top-1 -left-8 opacity-0 transition-opacity group-focus-within/block:opacity-100 group-hover/block:opacity-100">
        <Menu
          align="left"
          width={140}
          trigger={({ toggle }) => (
            <button type="button" onClick={toggle} aria-label={`${TYPE_LABEL[b.t]}操作`} className="flex size-6 items-center justify-center rounded-[5px] text-muted hover:bg-soft hover:text-ink">
              <GripVertical className="size-3.5" />
            </button>
          )}
          items={[
            { key: 'up', label: '上移', icon: <ArrowUp className="size-3.5" />, onSelect: () => onMove(b.id, -1) },
            { key: 'down', label: '下移', icon: <ArrowDown className="size-3.5" />, onSelect: () => onMove(b.id, 1) },
            { key: 'del', label: `删除${TYPE_LABEL[b.t]}`, icon: <Trash2 className="size-3.5" />, danger: true, divider: true, onSelect: () => ctx.remove(b.id) },
          ]}
        />
      </div>
      {body}
    </div>
  );
}
