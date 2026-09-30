import { ImageIcon } from 'lucide-react';
import { useEffect, useState } from 'react';

import { cn } from '@/lib/cn';

import { blogApi, type BlogPost } from './api';

/** 列表不返回封面地址：只为有封面的文章按需拉取 COVER 资源（同一会话内缓存） */
const cache = new Map<number, Promise<string | null>>();

export function coverUrl(post: Pick<BlogPost, 'id' | 'coverAssetId'>): Promise<string | null> {
  if (!post.coverAssetId) return Promise.resolve(null);
  const key = post.coverAssetId;
  if (!cache.has(key))
    cache.set(
      key,
      blogApi
        .assets(post.id, 'COVER')
        .then((list) => list.find((a) => a.id === post.coverAssetId)?.publicUrl ?? null)
        .catch(() => {
          cache.delete(key);
          return null;
        }),
    );
  return cache.get(key)!;
}

export function CoverThumb({ post, className }: { post: Pick<BlogPost, 'id' | 'coverAssetId'>; className?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    void coverUrl(post).then((u) => alive && setUrl(u));
    return () => {
      alive = false;
    };
  }, [post]);
  return (
    <div className={cn('flex shrink-0 items-center justify-center overflow-hidden rounded-[8px] border border-line bg-soft', className)}>
      {url ? <img src={url} alt="" className="size-full object-cover" /> : <ImageIcon aria-hidden className="size-4 text-muted" />}
    </div>
  );
}
