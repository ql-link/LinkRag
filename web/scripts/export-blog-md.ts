/**
 * 把 src/pages/blog/posts.ts 的静态文章导出为 Markdown（含 front matter），用于导入博客后台：
 *   node --import tsx scripts/export-blog-md.ts [输出目录，默认 dist-blog]
 * 后台新建文章 → 上传对应 .md（POST /api/v1/admin/blog/posts/{id}/content/import）→ 发布。
 * 标题与摘要在后台单独填写，这里一并写入 index.tsv 便于对照。
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { toMarkdown } from '../src/pages/blog/markdown';
import { sortPosts, STATIC_POSTS } from '../src/pages/blog/posts';

const out = process.argv[2] ?? 'dist-blog';
mkdirSync(out, { recursive: true });
const index = ['file\ttitle\tsummary\tdate'];
for (const p of sortPosts(STATIC_POSTS).reverse()) {
  writeFileSync(join(out, `${p.slug}.md`), toMarkdown(p));
  index.push(`${p.slug}.md\t${p.title}\t${p.lead}\t${p.date}`);
}
writeFileSync(join(out, 'index.tsv'), index.join('\n') + '\n');
console.log(`已导出 ${STATIC_POSTS.length} 篇到 ${out}/`);
