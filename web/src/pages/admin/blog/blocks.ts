/**
 * 编辑器块模型 ↔ Markdown。
 *
 * 语法与官网渲染器（src/pages/blog/markdown.ts）保持一致：front matter 原样保留；
 * `#`–`######` 标题（`## 标题 {#id}` 为章节锚点）、`---` 分隔线、GFM 表格（下一行 `: 说明` 为表注）、`> **标签** 文字` 提示框、
 * 单独一行的图片、``` 代码块（含 setup / bars 自定义块，按代码块原样保留）。
 */

export type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;

export type EBlock =
  | { id: string; t: 'p'; text: string }
  | { id: string; t: 'h'; level: HeadingLevel; text: string; anchor?: string }
  | { id: string; t: 'list'; ordered: boolean; items: string[] }
  | { id: string; t: 'quote'; text: string }
  | { id: string; t: 'callout'; label: string; text: string }
  | { id: string; t: 'code'; lang: string; text: string }
  | { id: string; t: 'table'; head: string[]; rows: string[][]; caption?: string }
  | { id: string; t: 'img'; alt: string; src: string; uploading?: boolean }
  | { id: string; t: 'hr' }
  /** 正在以源码编辑的文本块（Typora 式：聚焦时显示 Markdown，失焦后重新解析为上面的块） */
  | { id: string; t: 'md'; src: string };

export type BlockType = EBlock['t'];

export interface Doc {
  /** 含首尾 `---` 的原始 front matter；没有时为 null */
  frontMatter: string | null;
  blocks: EBlock[];
}

type Without<T> = T extends unknown ? Omit<T, 'id'> : never;
export type BlockInit = Without<EBlock>;

let seq = 0;
export const newId = () => `b${Date.now().toString(36)}${(seq++).toString(36)}`;
export const block = (b: BlockInit): EBlock => ({ ...b, id: newId() }) as EBlock;

const FM = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/;
const FENCE_OPEN = /^```\s*([\w+#.-]*)\s*$/;
const FENCE_CLOSE = /^```\s*$/;
const HEADING = /^(#{1,6})(?:[ \t]+(.*?))?[ \t]*(?:\{#([\w-]+)\})?[ \t]*$/;
const HR = /^(?:-{3,}|\*{3,}|_{3,})\s*$/;
const UL = /^\s*[-*]\s+/;
const OL = /^\s*\d+[.)]\s+/;
const IMG = /^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/;
const TABLE_SEP = /^:?-{2,}:?$/;

const splitRow = (line: string) =>
  line
    .trim()
    .replace(/^\||\|$/g, '')
    .split('|')
    .map((c) => c.trim());

const startsBlock = (line: string) => FENCE_OPEN.test(line) || HEADING.test(line) || HR.test(line) || line.trimStart().startsWith('|') || line.startsWith('>') || UL.test(line) || OL.test(line) || IMG.test(line.trim());

export function parseDoc(src: string): Doc {
  const text = src.replace(/\r\n/g, '\n');
  const fm = FM.exec(text);
  const frontMatter = fm ? fm[0].replace(/\n$/, '') : null;
  return { frontMatter, blocks: parseBody(fm ? text.slice(fm[0].length) : text) };
}

/** 正文（不含 front matter）→ 块 */
export function parseBody(src: string): EBlock[] {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const blocks: EBlock[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const fence = FENCE_OPEN.exec(line);
    if (fence) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE_CLOSE.test(lines[i])) body.push(lines[i++]);
      i += 1;
      blocks.push(block({ t: 'code', lang: fence[1] || '', text: body.join('\n') }));
      continue;
    }
    const h = HEADING.exec(line);
    if (h) {
      blocks.push(block({ t: 'h', level: h[1].length as HeadingLevel, text: h[2] ?? '', ...(h[3] ? { anchor: h[3] } : {}) }));
      i += 1;
      continue;
    }
    if (HR.test(line)) {
      blocks.push(block({ t: 'hr' }));
      i += 1;
      continue;
    }
    if (line.trimStart().startsWith('|')) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trimStart().startsWith('|')) {
        const cells = splitRow(lines[i]);
        if (!cells.every((c) => TABLE_SEP.test(c))) rows.push(cells);
        i += 1;
      }
      let j = i;
      while (j < lines.length && !lines[j].trim()) j += 1;
      let caption: string | undefined;
      if (j < lines.length && lines[j].startsWith(': ')) {
        caption = lines[j].slice(2).trim();
        i = j + 1;
      }
      const head = rows[0] ?? [''];
      const width = Math.max(head.length, ...rows.map((r) => r.length));
      const pad = (r: string[]) => [...r, ...Array<string>(width - r.length).fill('')];
      blocks.push(block({ t: 'table', head: pad(head), rows: rows.slice(1).map(pad), ...(caption ? { caption } : {}) }));
      continue;
    }
    if (UL.test(line) || OL.test(line)) {
      const ordered = !UL.test(line);
      const re = ordered ? OL : UL;
      const items: string[] = [];
      while (i < lines.length && re.test(lines[i])) items.push(lines[i++].replace(re, '').trim());
      blocks.push(block({ t: 'list', ordered, items }));
      continue;
    }
    if (line.startsWith('>')) {
      const parts: string[] = [];
      while (i < lines.length && lines[i].startsWith('>')) parts.push(lines[i++].replace(/^>\s?/, ''));
      const body = parts.join('\n').trim();
      const label = /^\*\*(.+?)\*\*\s*/.exec(body);
      blocks.push(label ? block({ t: 'callout', label: label[1], text: body.slice(label[0].length) }) : block({ t: 'quote', text: body }));
      continue;
    }
    const img = IMG.exec(line.trim());
    if (img) {
      blocks.push(block({ t: 'img', alt: img[1], src: img[2] }));
      i += 1;
      continue;
    }
    const para: string[] = [line.trim()];
    i += 1;
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i])) para.push(lines[i++].trim());
    blocks.push(block({ t: 'p', text: para.join('\n') }));
  }
  return blocks;
}

/** 可切换为源码编辑的文本块 */
export const isTextBlock = (b: { t: BlockType }) => b.t === 'p' || b.t === 'h' || b.t === 'list' || b.t === 'quote' || b.t === 'callout';

/** 文本块 → 源码编辑态 */
export function toMd(b: EBlock): EBlock {
  return isTextBlock(b) ? { id: b.id, t: 'md', src: serializeBlock(b) } : b;
}

/** 源码编辑态 → 重新解析的块（首块沿用原 id，便于保持焦点与大纲定位）；空源码为空段落 */
export function fromMd(b: EBlock): EBlock[] {
  if (b.t !== 'md') return [b];
  const parsed = parseBody(b.src);
  if (!parsed.length) return [{ id: b.id, t: 'p', text: '' }];
  return parsed.map((x, i) => (i === 0 ? ({ ...x, id: b.id } as EBlock) : x));
}

const settled = (list: EBlock[]) => list.flatMap(fromMd);

const cell = (s: string) => s.replace(/\|/g, '\\|').replace(/\n/g, ' ');
const quoteLines = (s: string) =>
  s
    .split('\n')
    .map((l) => (l ? `> ${l}` : '>'))
    .join('\n');

export function serializeBlock(b: EBlock): string {
  switch (b.t) {
    case 'p':
      return b.text.trim();
    case 'h':
      return `${'#'.repeat(b.level)} ${b.text.trim()}${b.anchor ? ` {#${b.anchor}}` : ''}`;
    case 'list':
      return b.items.map((it, n) => `${b.ordered ? `${n + 1}.` : '-'} ${it}`).join('\n');
    case 'quote':
      return quoteLines(b.text.trim());
    case 'callout':
      return quoteLines(`**${b.label.trim() || '提示'}** ${b.text.trim()}`);
    case 'code':
      return ['```' + b.lang, b.text, '```'].join('\n');
    case 'table': {
      const rows = [`| ${b.head.map(cell).join(' | ')} |`, `| ${b.head.map(() => '---').join(' | ')} |`, ...b.rows.map((r) => `| ${r.map(cell).join(' | ')} |`)];
      return rows.join('\n') + (b.caption?.trim() ? `\n: ${b.caption.trim()}` : '');
    }
    case 'img':
      return `![${b.alt.replace(/[[\]]/g, '')}](${b.src})`;
    case 'hr':
      return '---';
    case 'md':
      return fromMd(b)
        .filter((x) => !isBlank(x))
        .map(serializeBlock)
        .join('\n\n');
  }
}

/** 空块（未填写的段落、正在上传的图片）不写入正文 */
export function isBlank(b: EBlock): boolean {
  if (b.t === 'md') return fromMd(b).every(isBlank);
  if (b.t === 'img') return !!b.uploading || !b.src;
  if (b.t === 'p' || b.t === 'h' || b.t === 'quote') return !b.text.trim();
  if (b.t === 'list') return b.items.every((it) => !it.trim());
  return false;
}

export function serializeDoc(doc: Doc): string {
  const body = settled(doc.blocks)
    .filter((b) => !isBlank(b))
    .map(serializeBlock)
    .join('\n\n');
  const out = [doc.frontMatter, body].filter((s) => s && s.trim()).join('\n\n');
  return out ? `${out}\n` : '';
}

/** 纯文本字数（去掉 Markdown 标记与空白），用于状态栏 */
export function countChars(doc: Doc): number {
  const text = settled(doc.blocks)
    .filter((b) => b.t !== 'img' && b.t !== 'code' && b.t !== 'hr')
    .map((b) => (b.t === 'table' ? [...b.head, ...b.rows.flat()].join('') : b.t === 'list' ? b.items.join('') : 'text' in b ? b.text : ''))
    .join('');
  return text.replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*_`~#>|\s-]/g, '').length;
}
