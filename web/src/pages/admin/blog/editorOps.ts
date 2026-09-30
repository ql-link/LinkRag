/** 块列表的纯函数操作 + 源码编辑态的回车 / 标题快捷键 */
import { block, fromMd, isTextBlock, serializeBlock, type BlockInit, type BlockType, type EBlock, type HeadingLevel } from './blocks';

export function updateBlock(list: EBlock[], id: string, patch: Partial<EBlock>): EBlock[] {
  return list.map((b) => (b.id === id ? ({ ...b, ...patch } as EBlock) : b));
}

export function replaceBlock(list: EBlock[], id: string, next: EBlock): EBlock[] {
  return list.map((b) => (b.id === id ? next : b));
}

export function insertAfter(list: EBlock[], id: string | null, ...items: EBlock[]): EBlock[] {
  const at = id ? list.findIndex((b) => b.id === id) : list.length - 1;
  return [...list.slice(0, at + 1), ...items, ...list.slice(at + 1)];
}

export function removeBlock(list: EBlock[], id: string): EBlock[] {
  const next = list.filter((b) => b.id !== id);
  return next.length ? next : [block({ t: 'p', text: '' })];
}

export function moveBlock(list: EBlock[], id: string, delta: -1 | 1): EBlock[] {
  const at = list.findIndex((b) => b.id === id);
  const to = at + delta;
  if (at < 0 || to < 0 || to >= list.length) return list;
  const next = [...list];
  [next[at], next[to]] = [next[to], next[at]];
  return next;
}

/** 斜杠菜单创建的新块 */
export function blankBlock(t: BlockType, opts: { level?: HeadingLevel; ordered?: boolean; text?: string } = {}): BlockInit {
  switch (t) {
    case 'h':
      return { t: 'h', level: opts.level ?? 2, text: opts.text ?? '' };
    case 'list':
      return { t: 'list', ordered: !!opts.ordered, items: [opts.text ?? ''] };
    case 'quote':
      return { t: 'quote', text: opts.text ?? '' };
    case 'callout':
      return { t: 'callout', label: '提示', text: opts.text ?? '' };
    case 'code':
      return { t: 'code', lang: '', text: opts.text ?? '' };
    case 'table':
      return { t: 'table', head: ['', '', ''], rows: [['', '', ''], ['', '', '']] };
    case 'img':
      return { t: 'img', alt: '', src: '' };
    case 'hr':
      return { t: 'hr' };
    default:
      return { t: 'p', text: opts.text ?? '' };
  }
}

/** 新建的文本块直接进入源码编辑态；空标题 / 引用保留标记后的空格，光标落在标记之后 */
export function starter(next: BlockInit): BlockInit {
  if (!isTextBlock(next)) return next;
  let src = serializeBlock({ ...next, id: '' } as EBlock);
  if ((next.t === 'quote' || next.t === 'callout') && !next.text.trim()) src += ' ';
  return { t: 'md', src };
}

/** 除 keep 以外的源码块全部解析回普通块 */
export function settle(list: EBlock[], keep?: string): EBlock[] {
  return list.flatMap((b) => (b.t === 'md' && b.id !== keep ? fromMd(b) : [b]));
}

/** 源码编辑态下回车的处理方式 */
export type EnterAction =
  /** 块内续行（列表项 / 引用） */
  | { kind: 'insert'; text: string; caret: number }
  /** 在光标处拆成两块，后半段成为新段落 */
  | { kind: 'split'; before: string; after: string }
  /** 空列表项 / 空引用行：退出，在其后插入空段落 */
  | { kind: 'exit'; before: string; after: string }
  | { kind: 'code'; lang: string }
  | { kind: 'table'; head: string[] }
  | { kind: 'hr' };

const LIST_MARK = /^([ \t]*)(?:([-*+])|(\d+)([.)]))[ \t]+/;
const QUOTE_MARK = /^>[ \t]?/;

export function mdEnter(src: string, start: number, end = start): EnterAction {
  const before = src.slice(0, start);
  const after = src.slice(end);
  if (!after.trim() && !before.includes('\n')) {
    const fence = /^```([\w+#.-]*)\s*$/.exec(before);
    if (fence) return { kind: 'code', lang: fence[1] };
    if (/^(?:-{3,}|\*{3,}|_{3,})\s*$/.test(before)) return { kind: 'hr' };
    const row = before.trim();
    if (/^\|.*\|$/.test(row) && row.length > 2) {
      const head = row
        .replace(/^\||\|$/g, '')
        .split('|')
        .map((c) => c.trim());
      return { kind: 'table', head };
    }
  }
  const lineStart = before.lastIndexOf('\n') + 1;
  const nl = after.indexOf('\n');
  const lineEnd = end + (nl < 0 ? after.length : nl);
  const line = src.slice(lineStart, lineEnd);
  const li = LIST_MARK.exec(line);
  const q = li ? null : QUOTE_MARK.exec(line);
  const mark = li?.[0] ?? q?.[0];
  if (mark !== undefined) {
    if (!line.slice(mark.length).trim()) return { kind: 'exit', before: src.slice(0, lineStart).replace(/\n$/, ''), after: src.slice(lineEnd).replace(/^\n/, '') };
    const next = li ? `${li[1]}${li[2] ?? `${Number(li[3]) + 1}${li[4]}`} ` : '> ';
    return { kind: 'insert', text: `${before}\n${next}${after}`, caret: start + 1 + next.length };
  }
  return { kind: 'split', before, after };
}

/** ⌘1–6 设为对应级别标题，⌘0 恢复为段落（只改首行标记） */
export function setHeadingLevel(src: string, level: number): string {
  const body = src.replace(/^#{1,6}[ \t]*/, '');
  return level ? `${'#'.repeat(level)} ${body}` : body;
}

/** 大纲：一至三级标题（含正在编辑的源码块） */
export function outline(list: EBlock[]) {
  return list
    .flatMap((b) => (b.t === 'md' ? fromMd(b).slice(0, 1) : [b]))
    .filter((b): b is Extract<EBlock, { t: 'h' }> => b.t === 'h' && b.level <= 3 && !!b.text.trim())
    .map((b) => ({ id: b.id, level: b.level, text: b.text }));
}

/** 正文中引用到的图片地址（用于发布前检查、插图库「未使用」提示） */
export function referencedUrls(markdown: string): Set<string> {
  const out = new Set<string>();
  for (const m of markdown.matchAll(/!\[[^\]]*\]\(([^)\s]+)\)/g)) out.add(m[1]);
  return out;
}
