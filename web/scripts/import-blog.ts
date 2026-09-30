/**
 * 把 src/pages/blog/posts.ts 的静态文章导入并发布到博客后台（B9 管理接口，需 ADMIN 账号）。
 * 后端需开启 B9_BLOG_WRITES_ENABLED=true。已存在同名标题的文章会跳过，可重复执行。
 *
 *   LINKRAG_ADMIN=<账号> LINKRAG_PASSWORD=<密码> node --import tsx scripts/import-blog.ts [后端地址，默认 http://127.0.0.1:8000]
 */
import { toMarkdown } from '../src/pages/blog/markdown';
import { sortPosts, STATIC_POSTS } from '../src/pages/blog/posts';

const base = (process.argv[2] ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const account = process.env.LINKRAG_ADMIN;
const password = process.env.LINKRAG_PASSWORD;
if (!account || !password) {
  console.error('请通过环境变量 LINKRAG_ADMIN / LINKRAG_PASSWORD 提供管理员账号');
  process.exit(1);
}

let token = '';

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(base + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { satoken: token } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => null);
  if (!res.ok || json?.code !== 200) throw new Error(`${method} ${path} → ${res.status} ${json?.message ?? ''}`);
  return json.data as T;
}

const login = await call<{ accessToken: string }>('POST', '/api/v1/auth/login', { account, password });
token = login.accessToken;

const existing = await call<{ items: { title: string }[] }>('GET', '/api/v1/admin/blog/posts?page=1&pageSize=100');
const titles = new Set(existing.items.map((p) => p.title));

// 按时间正序发布，公开列表按发布时间倒序，最终顺序与静态数据一致
for (const p of sortPosts(STATIC_POSTS).reverse()) {
  if (titles.has(p.title)) {
    console.log(`跳过（已存在）：${p.title}`);
    continue;
  }
  const created = await call<{ id: number }>('POST', '/api/v1/admin/blog/posts', { title: p.title, summary: p.lead });
  await call('PUT', `/api/v1/admin/blog/posts/${created.id}/content`, { contentMarkdown: toMarkdown(p) });
  await call('POST', `/api/v1/admin/blog/posts/${created.id}/publish`);
  console.log(`已发布 #${created.id}：${p.title}`);
}
