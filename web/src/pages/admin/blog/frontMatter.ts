/**
 * front matter 中「分类 / 标签」的读写。只改动这两行，其余键（series、figures 等）原样保留。
 * 语法见 src/pages/blog/markdown.ts。
 */

export const CATEGORIES = ['技术', '评测', '实践', '版本更新'] as const;

export interface PostMeta {
  category: string;
  tags: string[];
}

const inner = (fm: string | null) => (fm ? fm.replace(/^---\n?/, '').replace(/\n?---\s*$/, '') : '');

export function readMeta(fm: string | null): PostMeta {
  const lines = inner(fm).split('\n');
  const get = (key: string) => lines.map((l) => new RegExp(`^${key}:\\s*(.*)$`).exec(l.replace(/\s+#.*$/, ''))).find(Boolean)?.[1]?.trim() ?? '';
  const rawTags = get('tags');
  const arr = /^\[(.*)\]$/.exec(rawTags);
  const tags = (arr ? arr[1].split(',') : rawTags ? [rawTags] : []).map((s) => s.trim()).filter(Boolean);
  return { category: get('category'), tags };
}

function setLine(lines: string[], key: string, value: string | null): string[] {
  const at = lines.findIndex((l) => l.startsWith(`${key}:`));
  if (value === null) return at < 0 ? lines : lines.filter((_, i) => i !== at);
  const line = `${key}: ${value}`;
  if (at < 0) return [...lines, line];
  const next = [...lines];
  next[at] = line;
  return next;
}

/** 写回分类与标签；front matter 为空时返回 null（不产生空的 `---` 块） */
export function writeMeta(fm: string | null, meta: PostMeta): string | null {
  let lines = inner(fm)
    .split('\n')
    .filter((l, i, all) => l.trim() || i < all.length - 1);
  if (lines.length === 1 && !lines[0].trim()) lines = [];
  lines = setLine(lines, 'category', meta.category.trim() || null);
  lines = setLine(lines, 'tags', meta.tags.length ? `[${meta.tags.join(', ')}]` : null);
  if (!lines.some((l) => l.trim())) return null;
  return ['---', ...lines, '---'].join('\n');
}

export function parseTags(input: string): string[] {
  return [...new Set(input.split(/[,，、]/).map((s) => s.trim().replace(/[[\]]/g, '')).filter(Boolean))];
}
