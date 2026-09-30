import { cn } from '@/lib/cn';

import { CATEGORY_TONE, type Post } from './posts';

/** 文章封面：分类底色 + 细网格 + 大字（设计稿 Cover/*） */
export function Cover({ post, size, className }: { post: Post; size: 'lg' | 'sm'; className?: string }) {
  const tone = CATEGORY_TONE[post.category];
  const lg = size === 'lg';
  // 后台上传了封面图时直接用图片
  if (post.cover.image)
    return <img src={post.cover.image} alt="" loading="lazy" className={cn('object-cover', lg ? 'rounded-[23px]' : 'rounded-lg', className)} />;
  // 网格线：分类色 7% 不透明度
  const line = `${tone.fg}12`;
  return (
    <div
      aria-hidden
      style={{
        backgroundColor: tone.bg,
        color: tone.fg,
        backgroundImage: `linear-gradient(${line} 1px, transparent 1px), linear-gradient(90deg, ${line} 1px, transparent 1px)`,
        backgroundSize: lg ? '48px 48px' : '17px 17px',
        backgroundPosition: 'center',
      }}
      className={cn('relative flex flex-col justify-center overflow-hidden', lg ? 'rounded-[23px] px-12' : 'rounded-lg px-4', className)}
    >
      <span className={cn('font-medium', lg ? 'absolute top-9 left-12 text-[17px]' : 'absolute top-3 left-4 text-[10px]')}>{post.category}</span>
      <span className={cn('font-num leading-none font-semibold tracking-[-0.02em]', lg ? 'text-[clamp(56px,7vw,99px)]' : 'text-[26px] font-medium')}>{post.cover.figure}</span>
      {lg && post.cover.caption && <span className="mt-4 font-num text-[19px] font-medium">{post.cover.caption}</span>}
    </div>
  );
}

export function CategoryLabel({ post, className }: { post: Post; className?: string }) {
  return (
    <span style={{ color: CATEGORY_TONE[post.category].fg }} className={cn('font-medium', className)}>
      {post.category}
    </span>
  );
}


/** 数据加载中 / 失败时的占位 */
export function BlogStatus({ state }: { state: { status: 'loading' } | { status: 'error'; message: string; retry: () => void } }) {
  return (
    <div role={state.status === 'error' ? 'alert' : 'status'} className="mx-auto flex max-w-[1440px] flex-col items-center gap-2 px-5 py-28 text-center">
      {state.status === 'loading' ? (
        <>
          <span aria-hidden className="size-6 animate-spin rounded-full border-2 border-line border-t-brand" />
          <p className="mt-2 text-[14px] text-muted">正在加载文章…</p>
        </>
      ) : (
        <>
          <p className="text-[15px] font-medium text-ink">文章暂时加载不出来</p>
          <p className="text-[13px] text-muted">{state.message}</p>
          <button type="button" onClick={state.retry} className="mt-3 rounded-full border border-line bg-white px-4 py-2 text-[13px] font-medium text-ink hover:bg-[#fbfbf9]">
            重试
          </button>
        </>
      )}
    </div>
  );
}
