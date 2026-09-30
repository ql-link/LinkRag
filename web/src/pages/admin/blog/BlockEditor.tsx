import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { focusEl, pendingCaret, setEditHook, type BlockCtx } from './blockCtx';
import { block, isBlank, isTextBlock, serializeBlock, toMd, type BlockInit, type EBlock } from './blocks';
import { BlockView } from './BlockView';
import { insertAfter, moveBlock, removeBlock, replaceBlock, settle, starter, updateBlock } from './editorOps';
import { FormatBar, type Selection } from './FormatBar';
import { SlashMenu } from './SlashMenu';

interface Props {
  blocks: EBlock[];
  onChange: (updater: (prev: EBlock[]) => EBlock[]) => void;
  /** 上传图片到指定图片块（不存在时由调用方新建） */
  onUpload: (blockId: string, file: File) => void;
}

const focusKey = (b: EBlock) => (b.t === 'table' ? `${b.id}:0` : b.id);
const sourceOf = (b: EBlock) => (b.t === 'md' ? b.src : serializeBlock(b));

/**
 * 设计稿 C3 / C7 / C8 / C9：块编辑区（Typora 式实时渲染）。
 * 文本块默认渲染显示，点击后该块切换为 Markdown 源码编辑（同一时间只有一个源码块），失焦后重新解析渲染。
 * 拖入或粘贴图片会在当前块后插入图片块并上传。
 */
export function BlockEditor({ blocks, onChange, onUpload }: Props) {
  const [sel, setSel] = useState<Selection | null>(null);
  const [slash, setSlash] = useState<{ el: HTMLTextAreaElement; id: string; query: string } | null>(null);
  const latest = useRef(blocks);
  latest.current = blocks;

  const ctx = useMemo<BlockCtx>(
    () => ({
      update: (id, patch) => onChange((l) => updateBlock(l, id, patch)),
      // 新建的文本块直接进入源码态，其余源码块同时解析回渲染态
      replace: (id, next, pos) => {
        const nb = { ...starter(next), id } as EBlock;
        if (nb.t === 'md') pendingCaret.set(id, pos ?? 'end');
        onChange((l) => settle(replaceBlock(l, id, nb), id));
        focusEl(focusKey(nb), pos ?? 'end');
      },
      insertAfter: (id, next, pos) => {
        const nb = block(starter(next));
        if (nb.t === 'md') pendingCaret.set(nb.id, pos ?? 'end');
        onChange((l) => settle(insertAfter(l, id, nb), nb.id));
        focusEl(focusKey(nb), pos ?? 'end');
      },
      remove: (id) =>
        onChange((l) => {
          const at = l.findIndex((b) => b.id === id);
          const prev = l[at - 1];
          if (prev) focusEl(focusKey(prev), 'end');
          return removeBlock(l, id);
        }),
      // 段首退格：并入上一文本块的源码末尾；上一块是分隔线时删除分隔线，是图片 / 代码 / 表格时只移动焦点
      mergeUp: (id, text) =>
        onChange((l) => {
          const at = l.findIndex((b) => b.id === id);
          const prev = l[at - 1];
          if (!prev) return l;
          if (prev.t === 'hr') {
            focusEl(id, 0);
            return l.filter((b) => b.id !== prev.id);
          }
          if (prev.t !== 'md' && !isTextBlock(prev)) {
            focusEl(focusKey(prev), 'end');
            return text.trim() ? l : removeBlock(l, id);
          }
          const head = sourceOf(prev);
          pendingCaret.set(prev.id, head.length);
          focusEl(prev.id, head.length);
          return removeBlock(replaceBlock(l, prev.id, { id: prev.id, t: 'md', src: head + text }), id);
        }),
      focusNeighbor: (id, dir) => {
        const at = blocks.findIndex((b) => b.id === id);
        const nb = blocks[at + dir];
        if (nb) focusEl(focusKey(nb), dir < 0 ? 'end' : 0);
      },
      edit: (id) => onChange((l) => settle(l, id).map((b) => (b.id === id ? toMd(b) : b))),
      settle: (id) => onChange((l) => (l.some((b) => b.id === id && b.t === 'md') ? settle(l) : l)),
      onSelection: setSel,
      slash: (el, id, query) => setSlash(el ? { el, id, query } : null),
      uploadImage: onUpload,
    }),
    [blocks, onChange, onUpload],
  );

  // focusEl 落到渲染态文本块时，先切换为源码态
  useEffect(() => {
    setEditHook((key) => {
      const b = latest.current.find((x) => x.id === key);
      if (!b || !isTextBlock(b)) return false;
      ctx.edit(key);
      return true;
    });
    return () => setEditHook(null);
  }, [ctx]);

  const clearSel = useCallback(() => setSel(null), []);

  const pickSlash = useCallback(
    (next: BlockInit) => {
      if (!slash) return;
      ctx.replace(slash.id, next);
      setSlash(null);
    },
    [slash, ctx],
  );

  /** 在焦点所在块之后插入图片块并上传 */
  const insertImages = (files: File[], target: HTMLElement | null) => {
    const anchor = target?.closest<HTMLElement>('[data-block]')?.dataset.block ?? blocks[blocks.length - 1]?.id ?? null;
    let after = anchor;
    for (const f of files) {
      const nb = block({ t: 'img', alt: f.name.replace(/\.\w+$/, ''), src: '' });
      const at = after;
      onChange((l) => {
        const cur = l.find((b) => b.id === at);
        // 空段落直接替换为图片
        if (cur && (cur.t === 'p' || cur.t === 'md') && isBlank(cur)) return replaceBlock(l, cur.id, nb);
        return insertAfter(l, at, nb);
      });
      after = nb.id;
      onUpload(nb.id, f);
    }
  };

  const images = (list: DataTransferItemList | FileList | null) => [...(list ?? [])].map((x) => (x instanceof File ? x : x.kind === 'file' ? x.getAsFile() : null)).filter((f): f is File => !!f && f.type.startsWith('image/'));

  return (
    <div
      className="flex flex-col gap-3.5 pb-24"
      onPaste={(e) => {
        const files = images(e.clipboardData.items);
        if (!files.length) return;
        e.preventDefault();
        insertImages(files, e.target as HTMLElement);
      }}
      onDragOver={(e) => [...e.dataTransfer.types].includes('Files') && e.preventDefault()}
      onDrop={(e) => {
        const files = images(e.dataTransfer.files);
        if (!files.length) return;
        e.preventDefault();
        insertImages(files, e.target as HTMLElement);
      }}
    >
      {blocks.map((b, i) => (
        <BlockView key={b.id} b={b} ctx={ctx} first={i === 0} onMove={(id, d) => onChange((l) => moveBlock(l, id, d))} />
      ))}
      <button
        type="button"
        onClick={() => {
          const last = blocks[blocks.length - 1];
          // 末尾已是空段落时直接编辑它
          if (last.t === 'p' && isBlank(last)) focusEl(last.id, 0);
          else ctx.insertAfter(last.id, { t: 'p', text: '' }, 0);
        }} className="h-10 cursor-text text-left text-[13px] text-transparent hover:text-muted" aria-label="在末尾添加段落">
        点击此处继续输入
      </button>
      {sel && sel.el.isConnected && <FormatBar sel={sel} onDone={clearSel} />}
      {slash && slash.el.isConnected && <SlashMenu anchor={slash.el} query={slash.query} onPick={pickSlash} onClose={() => setSlash(null)} />}
    </div>
  );
}
