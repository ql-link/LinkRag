import type { BlogPost, PostStatus } from './api';

export type StatusFilter = 'ALL' | PostStatus;
export type SortKey = 'updated' | 'created' | 'title';

export const SORT_LABEL: Record<SortKey, string> = { updated: '最近更新', created: '最近创建', title: '按标题' };

export function parseStatus(v: string | null): StatusFilter {
  return v === 'DRAFT' || v === 'PUBLISHED' ? v : 'ALL';
}

/** 客户端过滤（后端无关键词搜索）：标题 / Slug / 摘要，大小写不敏感 */
export function filterPosts(posts: BlogPost[], status: StatusFilter, keyword: string, sort: SortKey): BlogPost[] {
  const q = keyword.trim().toLowerCase();
  const out = posts.filter((p) => (status === 'ALL' || p.status === status) && (!q || [p.title, p.slug, p.summary ?? ''].some((s) => s.toLowerCase().includes(q))));
  const cmp: Record<SortKey, (a: BlogPost, b: BlogPost) => number> = {
    updated: (a, b) => b.updatedAt.localeCompare(a.updatedAt),
    created: (a, b) => b.createdAt.localeCompare(a.createdAt),
    title: (a, b) => a.title.localeCompare(b.title, 'zh-CN'),
  };
  return out.sort(cmp[sort]);
}

/** 从 Markdown 文件推断标题：front matter 后的第一个 `# 标题`，否则用文件名 */
export function titleFromMarkdown(text: string, filename: string): string {
  const body = text.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '');
  const h = /^#\s+(.+?)\s*$/m.exec(body);
  return (h?.[1] ?? filename.replace(/\.(md|markdown)$/i, '')).slice(0, 255) || '未命名文章';
}
