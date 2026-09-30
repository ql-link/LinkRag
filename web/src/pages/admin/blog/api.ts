/** 博客管理接口（Python `/api/v1/admin/blog`，ADMIN；写操作需开启 B9_BLOG_WRITES_ENABLED） */
import { ApiError, fetchAll, request } from '@/api/http';

export type PostStatus = 'DRAFT' | 'PUBLISHED';
export type AssetType = 'COVER' | 'CONTENT_IMAGE';

export interface BlogPost {
  id: number;
  title: string;
  slug: string;
  summary: string | null;
  contentObjectKey: string | null;
  coverAssetId: number | null;
  status: PostStatus;
  publishedAt: string | null;
  createdBy: number;
  createdAt: string;
  updatedAt: string;
  /** 仅详情接口返回 */
  contentMarkdown?: string | null;
}

export interface BlogAsset {
  id: number;
  postId: number;
  assetType: AssetType;
  originalFilename: string;
  contentType: string;
  fileSize: number;
  objectKey: string;
  publicUrl: string;
  createdBy: number;
  createdAt: string;
  updatedAt: string;
  markdownText: string | null;
}

const BASE = '/api/v1/admin/blog';
const post = (id: number) => `${BASE}/posts/${id}`;

export const ALLOWED_IMAGE = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

/** 上传前的本地校验，返回错误文案或 null */
export function checkImage(file: File): string | null {
  if (!ALLOWED_IMAGE.includes(file.type)) return '仅支持 JPG / PNG / GIF / WebP 图片';
  if (file.size > MAX_IMAGE_BYTES) return '图片不能超过 10 MB';
  return null;
}

export const blogApi = {
  listAll: () => fetchAll<BlogPost>(`${BASE}/posts`, {}, 100),
  get: (id: number) => request<BlogPost>(post(id)),
  create: (body: { title: string; summary?: string }) => request<BlogPost>(`${BASE}/posts`, { method: 'POST', body }),
  update: (id: number, body: { title?: string; summary?: string | null; coverAssetId?: number | null }) => request<BlogPost>(post(id), { method: 'PATCH', body }),
  saveContent: (id: number, contentMarkdown: string) => request<BlogPost>(`${post(id)}/content`, { method: 'PUT', body: { contentMarkdown } }),
  importMarkdown: (id: number, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return request<BlogPost>(`${post(id)}/content/import`, { method: 'POST', body: fd });
  },
  publish: (id: number) => request<BlogPost>(`${post(id)}/publish`, { method: 'POST' }),
  unpublish: (id: number) => request<BlogPost>(`${post(id)}/unpublish`, { method: 'POST' }),
  remove: (id: number) => request<null>(post(id), { method: 'DELETE' }),
  assets: (id: number, assetType?: AssetType) => request<BlogAsset[]>(`${post(id)}/assets`, { query: { assetType } }),
  upload: (id: number, assetType: AssetType, file: File) => {
    const fd = new FormData();
    fd.append('assetType', assetType);
    fd.append('file', file);
    return request<BlogAsset>(`${post(id)}/assets`, { method: 'POST', body: fd });
  },
  removeAsset: (id: number, assetId: number) => request<null>(`${post(id)}/assets/${assetId}`, { method: 'DELETE' }),
};

/** 把接口错误转成可读文案；503 = B9 写开关关闭 */
export function errMsg(e: unknown, fallback = '操作失败'): string {
  if (e instanceof ApiError) {
    if (e.status === 503) return '博客写入暂未开启（B9），请联系运维后重试';
    return e.message || fallback;
  }
  return (e as Error)?.message || fallback;
}

export function fileSize(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}
