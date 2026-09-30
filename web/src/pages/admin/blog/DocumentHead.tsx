import { ImageIcon } from 'lucide-react';

import { AutoTextarea } from './AutoTextarea';
import { focusEl } from './blockCtx';
import type { BlogPost } from './api';

interface Props {
  post: BlogPost | null;
  coverUrl: string | null;
  title: string;
  summary: string;
  onTitle: (v: string) => void;
  onSummary: (v: string) => void;
  onCover: () => void;
  /** 标题 / 摘要里按 Enter 跳到正文首块 */
  firstBlockKey: string | null;
}

/** 文档头部：封面 · 标题 · Slug · 摘要（设计稿 C3 / C4） */
export function DocumentHead({ post, coverUrl, title, summary, onTitle, onSummary, onCover, firstBlockKey }: Props) {
  return (
    <div className="flex flex-col gap-3">
      {coverUrl ? (
        <div className="group relative h-[190px] overflow-hidden rounded-[14px] border border-line bg-soft">
          <img src={coverUrl} alt="文章封面" className="size-full object-cover" />
          <button type="button" onClick={onCover} className="absolute right-3 bottom-3 flex items-center gap-1.5 rounded-[7px] bg-white/95 px-3 py-1.5 text-[12px] text-text2 opacity-0 shadow-seg transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
            <ImageIcon aria-hidden className="size-3.5" />
            更换封面
          </button>
        </div>
      ) : (
        <button type="button" onClick={onCover} className="flex w-fit items-center gap-1.5 rounded-[7px] px-2 py-1 text-[12px] text-muted hover:bg-soft hover:text-text2">
          <ImageIcon aria-hidden className="size-3.5" />
          添加封面
        </button>
      )}
      <AutoTextarea
        value={title}
        onChange={(e) => onTitle(e.target.value.replace(/\n/g, ''))}
        onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), focusEl('summary', 'end'))}
        maxLength={255}
        placeholder="文章标题"
        aria-label="文章标题"
        className="font-serif text-[32px] leading-tight font-semibold text-ink"
      />
      <p className="flex items-center gap-1.5 text-[11.5px] text-muted">
        <span className="font-num">/blogs/{post ? <span className="text-text2">{post.slug}</span> : '保存后自动生成'}</span>
        <span>·</span>
        <span>标题与摘要可直接编辑，Slug 由系统生成</span>
      </p>
      <AutoTextarea
        data-focus="summary"
        value={summary}
        onChange={(e) => onSummary(e.target.value.replace(/\n/g, ''))}
        onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), firstBlockKey && focusEl(firstBlockKey, 0))}
        placeholder="一句话摘要（显示在官网列表与分享卡片中）"
        aria-label="文章摘要"
        className="text-[15px] leading-relaxed text-text2"
      />
      <div className="mt-2 h-px bg-divider" />
    </div>
  );
}
