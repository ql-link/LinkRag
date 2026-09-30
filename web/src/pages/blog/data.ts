/**
 * 博客数据加载：真实后端读 B9 公开接口，Mock 模式用 posts.ts 的静态演示文章。
 *
 * 列表接口不含正文，而分类 / 标签 / 专题写在正文 front matter 里，所以列表加载后并发拉取各篇详情
 * （博客量级小，一次最多 100 篇）；结果在页面间缓存，列表 → 详情 → 返回不重复请求。
 */

import { useEffect, useState } from 'react';

import { request, USE_MOCK, type Page } from '@/api/http';

import { fromMarkdown, type RemotePost } from './markdown';
import { AUTHOR, makeBlogData, STATIC_POSTS, type BlogData } from './posts';

const LIST_LIMIT = 100;

async function loadRemote(): Promise<BlogData> {
  const list = await request<Page<RemotePost>>('/api/v1/blog/posts', { anonymous: true, query: { page: 1, pageSize: LIST_LIMIT } });
  const details = await Promise.all(
    list.items.map((it) =>
      request<RemotePost>(`/api/v1/blog/posts/${encodeURIComponent(it.slug)}`, { anonymous: true })
        // 单篇正文读取失败时仍展示在列表里（只有标题与摘要）
        .catch(() => it),
    ),
  );
  return makeBlogData(details.map((d) => fromMarkdown(d, AUTHOR.name)));
}

let cache: Promise<BlogData> | undefined;

export function loadBlog(): Promise<BlogData> {
  cache ??= (USE_MOCK ? Promise.resolve(makeBlogData(STATIC_POSTS)) : loadRemote()).catch((e) => {
    cache = undefined; // 失败不缓存，重试时重新请求
    throw e;
  });
  return cache;
}

export type BlogState = { status: 'loading' } | { status: 'error'; message: string; retry: () => void } | { status: 'ready'; data: BlogData };

export function useBlog(): BlogState {
  const [state, setState] = useState<BlogState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    loadBlog().then(
      (data) => alive && setState({ status: 'ready', data }),
      (e: Error) => alive && setState({ status: 'error', message: e.message || '文章加载失败', retry: () => (setState({ status: 'loading' }), setAttempt((n) => n + 1)) }),
    );
    return () => {
      alive = false;
    };
  }, [attempt]);
  return state;
}
