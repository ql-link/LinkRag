import type { BlockInit, EBlock } from './blocks';
import type { Selection } from './FormatBar';

/** 块组件与编辑器之间的回调约定 */
export interface BlockCtx {
  update: (id: string, patch: Partial<EBlock>) => void;
  /** 替换为新块并聚焦到 pos */
  replace: (id: string, next: BlockInit, pos?: number) => void;
  /** 在其后插入新块并聚焦 */
  insertAfter: (id: string, next: BlockInit, pos?: number) => void;
  /** 删除块，聚焦到上一块末尾 */
  remove: (id: string) => void;
  /** 把文本并入上一块末尾（段首 Backspace） */
  mergeUp: (id: string, text: string) => void;
  focusNeighbor: (id: string, dir: -1 | 1) => void;
  onSelection: (sel: Selection | null) => void;
  slash: (el: HTMLTextAreaElement | null, id: string, query: string) => void;
  uploadImage: (id: string, file: File) => void;
  /** 文本块切换为源码编辑（光标位置先写入 pendingCaret） */
  edit: (id: string) => void;
  /** 源码块失焦：重新解析为普通块 */
  settle: (id: string) => void;
}

/** 即将进入源码态的块应放置的光标（点击位置换算、focusEl 指定） */
export const pendingCaret = new Map<string, number | 'end'>();

/** 渲染态文本块：focusEl 时先切到源码态再聚焦 */
let editHook: ((id: string) => boolean) | null = null;
export function setEditHook(fn: typeof editHook) {
  editHook = fn;
}

/** 编辑器内可聚焦元素的标识：块 id，列表项为 `id:index` */
export const focusAttr = (id: string, index?: number) => ({ 'data-focus': index === undefined ? id : `${id}:${index}` });

export function focusEl(key: string, pos?: number | 'end') {
  requestAnimationFrame(() => {
    const el = document.querySelector<HTMLTextAreaElement | HTMLInputElement | HTMLElement>(`[data-focus="${CSS.escape(key)}"]`);
    if (!el) return;
    if (!('value' in el) && editHook) {
      // 渲染态文本块：记下光标，切到源码态后由 MdBlock 聚焦
      pendingCaret.set(key, pos ?? 'end');
      if (editHook(key)) return;
    }
    el.focus();
    if ('setSelectionRange' in el && pos !== undefined) {
      const p = pos === 'end' ? el.value.length : Math.min(pos, el.value.length);
      el.setSelectionRange(p, p);
    }
  });
}

/** 文本域的选区事件 → 格式栏 */
export function reportSelection(ctx: BlockCtx, el: HTMLTextAreaElement, apply: (text: string) => void) {
  const { selectionStart: start, selectionEnd: end } = el;
  ctx.onSelection(start !== end ? { el, start, end, apply } : null);
}

/** 快捷键：⌘B / ⌘I / ⌘E 行内代码 / ⌘K 链接由格式栏处理；这里只处理包裹类 */
export function hotkeyWrap(e: React.KeyboardEvent): [string, string] | null {
  if (!(e.metaKey || e.ctrlKey)) return null;
  const k = e.key.toLowerCase();
  if (k === 'b') return ['**', '**'];
  if (k === 'i') return ['*', '*'];
  if (k === 'e') return ['`', '`'];
  return null;
}
