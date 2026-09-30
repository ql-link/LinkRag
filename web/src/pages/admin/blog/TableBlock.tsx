import { MoreHorizontal } from 'lucide-react';

import { Menu } from '@/components/ui/Menu';
import { cn } from '@/lib/cn';

import { focusAttr, focusEl, type BlockCtx } from './blockCtx';
import type { EBlock } from './blocks';
import { insertCol, insertRow, removeCol, removeRow, setCell, type Grid } from './tableOps';

type TableB = Extract<EBlock, { t: 'table' }>;

/** 设计稿 C10：表格网格。单元格直接输入，Tab 跳格，右侧菜单增删行列 */
export function TableBlock({ b, ctx }: { b: TableB; ctx: BlockCtx }) {
  const grid: Grid = { head: b.head, rows: b.rows };
  const set = (g: Grid) => ctx.update(b.id, { head: g.head, rows: g.rows });
  const cols = b.head.length;
  const all = [b.head, ...b.rows];
  const key = (r: number, c: number) => `${b.id}:${r * cols + c}`;

  const move = (r: number, c: number, dir: 1 | -1) => {
    let n = r * cols + c + dir;
    if (n >= all.length * cols) {
      set(insertRow(grid, all.length));
      n = all.length * cols;
    }
    if (n < 0) return;
    focusEl(`${b.id}:${n}`, 'end');
  };

  const menu = (r: number, c: number) => [
    { key: 'ra', label: '上方插入行', onSelect: () => set(insertRow(grid, r)) },
    { key: 'rb', label: '下方插入行', onSelect: () => set(insertRow(grid, r + 1)) },
    { key: 'cl', label: '左侧插入列', divider: true, onSelect: () => set(insertCol(grid, c)) },
    { key: 'cr', label: '右侧插入列', onSelect: () => set(insertCol(grid, c + 1)) },
    { key: 'dr', label: '删除该行', divider: true, danger: true, onSelect: () => set(removeRow(grid, r)) },
    { key: 'dc', label: '删除该列', danger: true, onSelect: () => set(removeCol(grid, c)) },
    { key: 'dt', label: '删除表格', danger: true, onSelect: () => ctx.remove(b.id) },
  ];

  return (
    <figure className="flex flex-col gap-1.5">
      <div className="overflow-x-auto rounded-[10px] border border-line">
        <table className="w-full border-collapse text-[13px]">
          <tbody>
            {all.map((row, r) => (
              <tr key={r} className={cn(r === 0 ? 'bg-soft' : 'border-t border-divider')}>
                {row.map((v, c) => (
                  <td key={c} className="group relative border-l border-divider first:border-l-0">
                    <input
                      {...focusAttr(key(r, c))}
                      value={v}
                      onChange={(e) => set(setCell(grid, r, c, e.target.value))}
                      onKeyDown={(e) => {
                        if (e.key === 'Tab') {
                          e.preventDefault();
                          move(r, c, e.shiftKey ? -1 : 1);
                        } else if (e.key === 'Enter') {
                          e.preventDefault();
                          if (r === all.length - 1) set(insertRow(grid, all.length));
                          focusEl(`${b.id}:${(r + 1) * cols + c}`);
                        }
                      }}
                      aria-label={r === 0 ? `表头第 ${c + 1} 列` : `第 ${r} 行第 ${c + 1} 列`}
                      placeholder={r === 0 ? '表头' : ''}
                      className={cn('w-full min-w-[80px] bg-transparent px-3 py-2 pr-7 outline-none focus:bg-blue/5', r === 0 ? 'font-medium text-ink' : 'text-text2')}
                    />
                    <div className="absolute top-1/2 right-1 -translate-y-1/2 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100">
                      <Menu
                        width={150}
                        trigger={({ toggle }) => (
                          <button type="button" onClick={toggle} aria-label="表格操作" className="flex size-5 items-center justify-center rounded-[4px] text-muted hover:bg-white hover:text-ink">
                            <MoreHorizontal className="size-3.5" />
                          </button>
                        )}
                        items={menu(r, c)}
                      />
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <input
        value={b.caption ?? ''}
        onChange={(e) => ctx.update(b.id, { caption: e.target.value || undefined })}
        placeholder="添加表注（可选）"
        aria-label="表注"
        className="bg-transparent text-center text-[12px] text-muted outline-none"
      />
    </figure>
  );
}
