import { Eye, PenLine, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Chip } from '@/components/ui/Chip';
import { cn } from '@/lib/cn';

import { relTime } from '../ui';
import type { BlogPost } from './api';
import { CoverThumb } from './CoverThumb';

const iconBtn = 'flex size-8 items-center justify-center rounded-[7px] border border-line bg-white text-text2 transition-colors hover:bg-soft disabled:opacity-40';

/** 设计稿 C1 文章行：封面 96×60 + 标题/状态/Slug/摘要 + 时间 + 预览/编辑/删除 */
export function PostRow({ post, onDelete }: { post: BlogPost; onDelete: (p: BlogPost) => void }) {
  const published = post.status === 'PUBLISHED';
  return (
    <li className="flex items-center gap-5 border-b border-divider py-3.5">
      <CoverThumb post={post} className="h-[60px] w-24" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 items-center gap-2">
          <Link to={`/admin/blog/${post.id}`} className="truncate text-[14px] font-medium text-ink hover:underline">
            {post.title || '未命名文章'}
          </Link>
          <Chip tone={published ? 'green' : 'gray'}>{published ? '已发布' : '草稿'}</Chip>
        </div>
        <p className="truncate font-num text-[11.5px] text-muted">/blogs/{post.slug}</p>
        <p className={cn('truncate text-[12px]', post.summary ? 'text-text2' : 'text-muted')}>{post.summary || '暂无摘要'}</p>
      </div>
      <div className="flex w-[120px] shrink-0 flex-col gap-1 text-right text-[11.5px]">
        <span className="text-text2">更新于 {relTime(post.updatedAt)}</span>
        <span className="text-muted">{published && post.publishedAt ? `发布于 ${relTime(post.publishedAt).replace(/ \d\d:\d\d$/, '')}` : '未发布'}</span>
      </div>
      <div className="flex shrink-0 gap-1.5">
        {published ? (
          <a href={`/blog/${encodeURIComponent(post.slug)}`} target="_blank" rel="noreferrer" aria-label={`预览「${post.title}」`} title="在官网查看" className={iconBtn}>
            <Eye aria-hidden className="size-3.5" />
          </a>
        ) : (
          <button type="button" disabled aria-label="草稿不可预览" title="草稿发布后可在官网查看" className={iconBtn}>
            <Eye aria-hidden className="size-3.5" />
          </button>
        )}
        <Link to={`/admin/blog/${post.id}`} aria-label={`编辑「${post.title}」`} title="编辑" className={iconBtn}>
          <PenLine aria-hidden className="size-3.5" />
        </Link>
        <button type="button" onClick={() => onDelete(post)} aria-label={`删除「${post.title}」`} title="删除" className={cn(iconBtn, 'hover:text-red')}>
          <Trash2 aria-hidden className="size-3.5" />
        </button>
      </div>
    </li>
  );
}
