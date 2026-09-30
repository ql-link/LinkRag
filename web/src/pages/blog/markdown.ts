/**
 * 博客 Markdown ↔ 结构化文章。
 *
 * 后端（B9）只存标题 / 摘要 / 封面 / 发布时间和 Markdown 正文；分类、标签、专题、关键数字等
 * 写在正文开头的 front matter 里，由前端解析。约定（均可省略）：
 *
 *   ---
 *   category: 评测              # 评测 / 技术 / 实践 / 版本更新，默认「技术」
 *   tags: [重排, Recall]
 *   series: eval                # 专题 id，见 posts.ts SERIES_META
 *   author: LinkRag 团队
 *   updated: 2026-09-30
 *   cover: 90.20% | Recall@10 · 接重排后   # 封面大字 | 说明（上传了封面图时以图片为准）
 *   report: r13                 # 对应评测报告 id，文末展示「本文数据」
 *   figures:
 *     - Recall@10 · 接重排后 | 90.20% | 同条件下 WeKnora 为 89.53%
 *   ---
 *
 * 正文按 `## 标题 {#id}` 切成章节；章节内支持段落、`###`–`######` 小标题、`-` / `1.` 列表、`---` 分隔线、
 * GFM 表格（下一行 `: 说明` 为表注）、`> 引用`、`> **标签** 文字` 提示框、单独一行的图片、代码块，
 * 行内支持粗体 / 斜体 / 删除线 / 行内代码 / 链接（见 lib/inlineMarkdown），以及两种自定义代码块：
 * ```setup（每行 `名称: 内容`）与 ```bars（JSON：legend / groups / caption）。
 */

import { plainInline } from '@/lib/inlineMarkdown';

import type { Block, Category, Post, Section } from './posts';

const CATEGORY_SET = new Set<Category>(['评测', '技术', '实践', '版本更新']);

type Meta = Record<string, string | string[]>;

function parseFrontMatter(src: string): { meta: Meta; body: string } {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(src);
  if (!m) return { meta: {}, body: src };
  const meta: Meta = {};
  let listKey: string | undefined;
  for (const raw of m[1].split(/\r?\n/)) {
    const line = raw.replace(/\s+#.*$/, '');
    if (!line.trim()) continue;
    const item = /^\s+-\s+(.*)$/.exec(line);
    if (item && listKey) {
      (meta[listKey] as string[]).push(item[1].trim());
      continue;
    }
    const kv = /^([\w-]+):\s*(.*)$/.exec(line);
    if (!kv) continue;
    const [, key, value] = kv;
    if (!value) {
      listKey = key;
      meta[key] = [];
    } else {
      listKey = undefined;
      const arr = /^\[(.*)\]$/.exec(value);
      meta[key] = arr ? arr[1].split(',').map((s) => s.trim()).filter(Boolean) : value.trim();
    }
  }
  return { meta, body: src.slice(m[0].length) };
}

const str = (v: string | string[] | undefined) => (typeof v === 'string' ? v : undefined);
const list = (v: string | string[] | undefined) => (Array.isArray(v) ? v : v ? [v] : []);

function parseBlocks(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    // 代码块
    const fence = /^```\s*([\w-]*)\s*$/.exec(line);
    if (fence) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) body.push(lines[i++]);
      i += 1;
      const lang = fence[1] || 'text';
      if (lang === 'setup') {
        const rows = body.filter((l) => l.trim()).map((l): [string, string] => {
          const at = l.search(/[:：]/);
          return at < 0 ? [l.trim(), ''] : [l.slice(0, at).trim(), l.slice(at + 1).trim()];
        });
        blocks.push({ t: 'setup', rows });
      } else if (lang === 'bars') {
        try {
          const b = JSON.parse(body.join('\n'));
          blocks.push({ t: 'bars', legend: b.legend, groups: b.groups, caption: b.caption ?? '' });
        } catch {
          blocks.push({ t: 'code', lang: 'json', lines: body });
        }
      } else blocks.push({ t: 'code', lang, lines: body });
      continue;
    }
    // 表格
    if (line.trimStart().startsWith('|')) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trimStart().startsWith('|')) {
        const cells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i += 1;
      }
      while (i < lines.length && !lines[i].trim()) i += 1;
      let caption: string | undefined;
      if (i < lines.length && lines[i].startsWith(': ')) caption = lines[i++].slice(2).trim();
      blocks.push({ t: 'table', head: rows[0] ?? [], rows: rows.slice(1), caption });
      continue;
    }
    // 小标题（章节内的 ### 及以下；# / ## 由 parseSections 处理）
    const h = /^(#{3,6})(?:[ \t]+(.*?))?[ \t]*(?:\{#[\w-]+\})?[ \t]*$/.exec(line);
    if (h) {
      if (h[2]?.trim()) blocks.push({ t: 'h', level: h[1].length, text: h[2].trim() });
      i += 1;
      continue;
    }
    // 分隔线
    if (/^(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push({ t: 'hr' });
      i += 1;
      continue;
    }
    // 列表
    const listRe = /^\s*[-*]\s+/.test(line) ? /^\s*[-*]\s+/ : /^\s*\d+[.)]\s+/.test(line) ? /^\s*\d+[.)]\s+/ : null;
    if (listRe) {
      const items: string[] = [];
      while (i < lines.length && listRe.test(lines[i])) items.push(lines[i++].replace(listRe, '').trim());
      blocks.push(listRe.source.includes('d') ? { t: 'list', items, ordered: true } : { t: 'list', items });
      continue;
    }
    // 提示框
    if (line.startsWith('>')) {
      const parts: string[] = [];
      while (i < lines.length && lines[i].startsWith('>')) parts.push(lines[i++].replace(/^>\s?/, ''));
      const text = parts.join('\n').trim();
      const label = /^\*\*(.+?)\*\*\s*/.exec(text);
      blocks.push(label ? { t: 'callout', label: label[1], text: text.slice(label[0].length).replace(/\n/g, ' ') } : { t: 'quote', text });
      continue;
    }
    // 单独一行的图片
    const img = /^!\[([^\]]*)\]\(([^)\s]+)\)\s*$/.exec(line.trim());
    if (img) {
      blocks.push({ t: 'img', alt: img[1], src: img[2] });
      i += 1;
      continue;
    }
    // 段落：连续非空行合并
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(```|\||>|\s*[-*]\s+|\s*\d+[.)]\s+|#{1,6}(\s|$)|(-{3,}|\*{3,}|_{3,})\s*$)/.test(lines[i])) para.push(lines[i++].trim());
    if (para.length) blocks.push({ t: 'p', text: para.join('') });
    else i += 1;
  }
  return blocks;
}

/** `#` / `##` 开启新章节；与文章标题相同的一级标题视为重复标题忽略 */
function parseSections(body: string, title = ''): Section[] {
  const sections: Section[] = [];
  let current: { id: string; title: string; lines: string[] } | undefined;
  const intro: string[] = [];
  const flush = () => current && sections.push({ id: current.id, title: current.title, blocks: parseBlocks(current.lines) });
  let inFence = false;
  for (const line of body.split(/\r?\n/)) {
    if (/^```/.test(line)) inFence = !inFence;
    const h = !inFence && /^(#{1,2})\s+(.+?)\s*(?:\{#([\w-]+)\})?\s*$/.exec(line);
    if (inFence || /^```/.test(line)) (current ? current.lines : intro).push(line);
    else if (h && h[1] === '#' && h[2].trim() === title.trim()) {
      // 与文章标题重复的一级标题
    } else if (h) {
      flush();
      current = { id: h[3] ?? `s${sections.length + 1}`, title: h[2], lines: [] };
    } else (current ? current.lines : intro).push(line);
  }
  flush();
  const introBlocks = parseBlocks(intro);
  if (introBlocks.length) sections.unshift({ id: 'intro', title: '导语', blocks: introBlocks });
  return sections;
}

export interface RemotePost {
  slug: string;
  title: string;
  summary: string | null;
  coverPublicUrl: string | null;
  publishedAt: string | null;
  contentMarkdown?: string;
}

/** 后端文章 → 结构化文章 */
export function fromMarkdown(remote: RemotePost, defaultAuthor: string): Post {
  const { meta, body } = parseFrontMatter(remote.contentMarkdown ?? '');
  const sections = parseSections(body, remote.title);
  const cat = str(meta.category) as Category | undefined;
  const [figure, caption] = (str(meta.cover) ?? '').split('|').map((s) => s.trim());
  const firstPara = sections.flatMap((s) => s.blocks).find((b): b is Extract<Block, { t: 'p' }> => b.t === 'p');
  const figures = list(meta.figures)
    .map((f) => f.split('|').map((s) => s.trim()))
    .filter((f) => f.length >= 2)
    .map(([label, value, note = '']) => ({ label, value, note }));
  const category = cat && CATEGORY_SET.has(cat) ? cat : '技术';
  return {
    slug: remote.slug,
    title: remote.title,
    lead: remote.summary?.trim() || (firstPara ? plainInline(firstPara.text) : ''),
    category,
    date: (remote.publishedAt ?? '').slice(0, 10),
    updated: str(meta.updated),
    author: str(meta.author) ?? defaultAuthor,
    tags: list(meta.tags),
    series: str(meta.series),
    cover: { figure: figure || category, caption: caption || undefined, image: remote.coverPublicUrl ?? undefined },
    figures: figures.length ? figures.slice(0, 3) : undefined,
    sections,
    reportId: str(meta.report),
  };
}

/** 结构化文章 → Markdown（用于把站内文章导入后台，也用于往返测试） */
export function toMarkdown(p: Post): string {
  const fm = ['---', `category: ${p.category}`];
  if (p.tags.length) fm.push(`tags: [${p.tags.join(', ')}]`);
  if (p.series) fm.push(`series: ${p.series}`);
  fm.push(`author: ${p.author}`);
  if (p.updated) fm.push(`updated: ${p.updated}`);
  fm.push(`cover: ${p.cover.figure}${p.cover.caption ? ` | ${p.cover.caption}` : ''}`);
  if (p.reportId) fm.push(`report: ${p.reportId}`);
  if (p.figures) fm.push('figures:', ...p.figures.map((f) => `  - ${f.label} | ${f.value} | ${f.note}`));
  fm.push('---', '');
  const out = [fm.join('\n')];
  for (const s of p.sections) {
    out.push(`## ${s.title} {#${s.id}}`, '');
    for (const b of s.blocks) {
      switch (b.t) {
        case 'p':
          out.push(b.text);
          break;
        case 'list':
          out.push(b.items.map((it, n) => `${b.ordered ? `${n + 1}.` : '-'} ${it}`).join('\n'));
          break;
        case 'h':
          out.push(`${'#'.repeat(b.level)} ${b.text}`);
          break;
        case 'quote':
          out.push(b.text.split('\n').map((l) => `> ${l}`).join('\n'));
          break;
        case 'hr':
          out.push('---');
          break;
        case 'setup':
          out.push(['```setup', ...b.rows.map(([k, v]) => `${k}: ${v}`), '```'].join('\n'));
          break;
        case 'bars':
          out.push(['```bars', JSON.stringify({ legend: b.legend, groups: b.groups, caption: b.caption }), '```'].join('\n'));
          break;
        case 'table':
          out.push([`| ${b.head.join(' | ')} |`, `| ${b.head.map(() => '---').join(' | ')} |`, ...b.rows.map((r) => `| ${r.join(' | ')} |`)].join('\n') + (b.caption ? `\n: ${b.caption}` : ''));
          break;
        case 'callout':
          out.push(`> **${b.label}** ${b.text}`);
          break;
        case 'img':
          out.push(`![${b.alt}](${b.src})`);
          break;
        case 'code':
          out.push(['```' + b.lang, ...b.lines, '```'].join('\n'));
          break;
      }
      out.push('');
    }
  }
  return out.join('\n');
}
