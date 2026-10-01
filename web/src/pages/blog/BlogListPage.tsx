import { Search, X } from 'lucide-react';
import { useEffect, useMemo, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { cn } from '@/lib/cn';
import { pill } from '@/pages/landing/shared';
import { PublicShell } from '@/pages/landing/SiteChrome';
import { RELEASES_URL } from '@/pages/research/data';

import { BlogStatus, CategoryLabel, Cover } from './components';
import { useBlog } from './data';
import { allTags, CATEGORIES, postText, readMinutes, type BlogData, type Category, type Post } from './posts';

/**
 * 博客列表（设计稿「10 博客 · V2 单栏」L11 v2）：全部区块居中于同一条 720 内容栏，
 * 依次为 刊头与搜索 → 分类页签 → 标签横排 → 头条卡片 → 纯文字文章列表 → 专题与关注更新。
 * 分类、标签、搜索词与页码写在 URL 查询参数里，便于分享与返回。
 */
const COL = 'mx-auto w-full max-w-[768px] px-5 md:px-6';
const PAGE_SIZE = 5;

export default function BlogListPage() {
  const state = useBlog();
  return <PublicShell>{state.status === 'ready' ? <BlogList data={state.data} /> : <BlogStatus state={state} />}</PublicShell>;
}

function BlogList({ data }: { data: BlogData }) {
  const [params, setParams] = useSearchParams();
  const category = (CATEGORIES as string[]).includes(params.get('c') ?? '') ? (params.get('c') as Category) : undefined;
  const tag = params.get('tag') ?? undefined;
  const q = params.get('q')?.trim() ?? '';
  const page = Math.max(1, Number(params.get('page')) || 1);

  const update = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) (v ? next.set(k, v) : next.delete(k));
    if (!('page' in patch)) next.delete('page');
    setParams(next, { replace: true });
  };

  const filtered = useMemo(() => {
    const needle = q.toLowerCase();
    return data.posts.filter((p) => (!category || p.category === category) && (!tag || p.tags.includes(tag)) && (!needle || postText(p).toLowerCase().includes(needle)));
  }, [data, category, tag, q]);

  // 无筛选的第一页：最新一篇作为头条，其余进入列表
  const plain = !category && !tag && !q;
  const featured = plain ? filtered[0] : undefined;
  const rest = featured ? filtered.slice(1) : filtered;
  const pages = Math.max(1, Math.ceil(rest.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const shown = rest.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  const goPage = (n: number) => {
    update({ page: n > 1 ? String(n) : undefined });
    document.getElementById('blog-list')?.scrollIntoView({ block: 'start' });
  };

  return (
    <>
      <Masthead q={q} onSearch={(v) => update({ q: v || undefined })} />
      <Tabs posts={data.posts} category={category} onChange={(c) => update({ c, tag: undefined })} />
      <TagRow tags={allTags(data.posts)} active={tag} onTag={(t) => update({ tag: t === tag ? undefined : t, c: undefined })} />
      {featured && current === 1 && <Featured post={featured} />}
      <div className={cn(COL, 'flex flex-col gap-14 pt-4 pb-24')}>
        <section id="blog-list" aria-labelledby="blog-list-title" className="scroll-mt-24">
          <div className="flex flex-wrap items-end gap-3 border-b border-divider pb-3">
            <h2 id="blog-list-title" className="font-serif text-[20px] font-semibold text-ink">
              {plain ? '最新文章' : `找到 ${filtered.length} 篇`}
            </h2>
            {tag && <FilterChip label={`标签：${tag}`} onClear={() => update({ tag: undefined })} />}
            {q && <FilterChip label={`搜索：${q}`} onClear={() => update({ q: undefined })} />}
            {plain && <span className="ml-auto pb-0.5 text-[12.5px] text-muted">{data.posts.length} 篇 · 按发布时间</span>}
          </div>
          {shown.length ? (
            <ul>
              {shown.map((p) => (
                <Row key={p.slug} post={p} />
              ))}
            </ul>
          ) : (
            <Empty none={data.posts.length === 0} onReset={() => setParams({}, { replace: true })} />
          )}
          {pages > 1 && <Pagination current={current} pages={pages} onChange={goPage} />}
        </section>
        <More data={data} />
      </div>
    </>
  );
}

function Masthead({ q, onSearch }: { q: string; onSearch: (v: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  // 「/」聚焦搜索框（输入框内不拦截）
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.key !== '/' || el.closest('input, textarea, [contenteditable]')) return;
      e.preventDefault();
      input.current?.focus();
    };
    document.addEventListener('keydown', on);
    return () => document.removeEventListener('keydown', on);
  }, []);
  return (
    <header className={cn(COL, 'flex flex-col gap-7 pt-12 pb-8 md:pt-20')}>
      <div className="flex flex-col gap-3.5">
        <h1 className="font-serif text-[clamp(32px,4.4vw,42px)] leading-[1.3] font-semibold tracking-[-0.01em] text-ink">检索这件事，我们做了什么</h1>
        <p className="text-[16px] leading-[28px] text-[#6b6a64] md:text-[16.5px]">
          评测复盘、技术笔记和版本更新。文章里的数字都能在
          <Link to="/research" className="text-[#a8733f] hover:underline">
            评测中心
          </Link>
          找到原始结果。
        </p>
      </div>
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          onSearch(input.current?.value.trim() ?? '');
        }}
        className="flex h-11 w-full items-center gap-2.5 rounded-xl border border-line bg-white px-[18px] transition-colors focus-within:border-brand"
      >
        <Search aria-hidden className="size-4 text-muted" />
        <input
          ref={input}
          key={q}
          type="search"
          defaultValue={q}
          placeholder="搜索文章标题、正文或标签"
          aria-label="搜索文章"
          className="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-muted [&::-webkit-search-cancel-button]:hidden"
        />
        <kbd className="hidden rounded-[5px] border border-line px-1.5 font-num text-[11px] font-medium text-muted md:block">/</kbd>
      </form>
    </header>
  );
}

function Tabs({ posts, category, onChange }: { posts: Post[]; category?: Category; onChange: (c?: Category) => void }) {
  const items: { c?: Category; label: string; n: number }[] = [{ label: '全部', n: posts.length }, ...CATEGORIES.map((c) => ({ c, label: c, n: posts.filter((p) => p.category === c).length }))];
  return (
    <div className={COL}>
      <div role="tablist" aria-label="文章分类" className="flex gap-[26px] overflow-x-auto overflow-y-hidden border-b border-divider [scrollbar-width:none]">
        {items.map((it) => {
          const on = it.c === category;
          return (
            <button
              key={it.label}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => onChange(it.c)}
              className={cn('-mb-px flex shrink-0 items-center gap-1.5 border-b-2 pb-3.5 text-[14.5px] transition-colors', on ? 'border-brand font-medium text-ink' : 'border-transparent text-text2 hover:text-ink')}
            >
              {it.label}
              <span className={cn('font-num text-[12px] font-medium', on ? 'text-[#a8733f]' : 'text-[#b5b4ac]')}>{it.n}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Byline({ post }: { post: Post }) {
  return (
    <span className="flex items-center gap-2.5">
      <span aria-hidden className="size-7 rounded-full bg-[#e8d9c3]" />
      <span className="text-[13.5px] font-medium text-ink">{post.author}</span>
      <span className="text-[13px] text-muted">· {readMinutes(post)} 分钟阅读</span>
    </span>
  );
}

/** 头条卡片：封面在上、文字在下 */
function Featured({ post }: { post: Post }) {
  return (
    <section aria-label="头条文章" className={cn(COL, 'pt-9 pb-12')}>
      <div className="group overflow-hidden rounded-[18px] border border-divider bg-white shadow-[0_8px_24px_rgba(0,0,0,0.04)]">
        <Link to={`/blog/${post.slug}`} tabIndex={-1} aria-hidden className="block overflow-hidden">
          <Cover post={post} size="lg" className="aspect-[720/280] rounded-none transition-transform duration-300 group-hover:scale-[1.01]" />
        </Link>
        <div className="flex flex-col gap-3.5 px-6 pt-6 pb-7 md:px-8 md:pt-7 md:pb-8">
          <p className="flex items-center gap-2.5 text-[13px]">
            <span className="rounded-full bg-brand px-[9px] py-[3px] text-[11.5px] font-medium text-white">最新</span>
            <CategoryLabel post={post} />
            <span className="text-faint">·</span>
            <time dateTime={post.date} className="font-num text-muted">
              {post.date}
            </time>
          </p>
          <h2 className="font-serif text-[clamp(24px,3vw,30px)] leading-[1.4] font-semibold tracking-[-0.005em] text-ink">
            <Link to={`/blog/${post.slug}`} className="hover:text-[#6b4a2a]">
              {post.title}
            </Link>
          </h2>
          <p className="line-clamp-3 text-[15.5px] leading-[27px] text-[#6b6a64] md:text-[16px]">{post.lead}</p>
          <div className="flex flex-wrap items-center justify-between gap-4 pt-2.5">
            <Byline post={post} />
            <Link to={`/blog/${post.slug}`} className="inline-flex items-center gap-2 rounded-full bg-ink px-[18px] py-2.5 text-[14px] font-medium text-white transition-colors hover:bg-[#35342f]">
              阅读全文 <span aria-hidden>→</span>
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/** 列表行：纯文字，标题 → 摘要 → 日期 · 分类 · 时长 · 作者 */
function Row({ post }: { post: Post }) {
  return (
    <li className="border-b border-divider">
      <Link to={`/blog/${post.slug}`} className="group flex flex-col gap-2.5 py-7">
        <span className="font-serif text-[19px] leading-[1.5] font-semibold text-ink transition-colors group-hover:text-[#6b4a2a] md:text-[20px]">{post.title}</span>
        <span className="line-clamp-2 text-[14.5px] leading-6 text-[#6b6a64]">{post.lead}</span>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-0.5 text-[12.5px]">
          <time dateTime={post.date} className="font-num font-medium text-muted">
            {post.date.replaceAll('-', '.')}
          </time>
          <span className="text-faint">·</span>
          <CategoryLabel post={post} />
          <span className="text-faint">·</span>
          <span className="text-muted">{readMinutes(post)} 分钟</span>
          <span className="text-faint">·</span>
          <span className="text-muted">{post.author}</span>
        </span>
      </Link>
    </li>
  );
}

function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="flex items-center gap-1 rounded-full bg-soft py-1 pr-1.5 pl-3 text-[12.5px] text-text2">
      {label}
      <button type="button" onClick={onClear} aria-label={`清除${label}`} className="flex size-5 items-center justify-center rounded-full hover:bg-active">
        <X aria-hidden className="size-3" />
      </button>
    </span>
  );
}

function Empty({ none, onReset }: { none: boolean; onReset: () => void }) {
  return (
    <div className="mt-4 flex flex-col items-center gap-2 rounded-2xl border border-dashed border-line bg-white px-6 py-14 text-center">
      <p className="text-[15px] font-medium text-ink">{none ? '还没有发布文章' : '没有找到相关文章'}</p>
      <p className="text-[13px] text-muted">{none ? '第一篇文章正在路上，发布后会出现在这里。' : '换个关键词，或查看全部文章。'}</p>
      {!none && <button type="button" onClick={onReset} className={cn(pill.secondary, 'mt-3 px-4 py-2 text-[13px]')}>
        查看全部
      </button>}
    </div>
  );
}

function Pagination({ current, pages, onChange }: { current: number; pages: number; onChange: (n: number) => void }) {
  const cell = 'flex h-[30px] min-w-[30px] items-center justify-center rounded-full px-2.5 font-num text-[13px] font-medium';
  return (
    <nav aria-label="分页" className="flex items-center gap-1.5 pt-8">
      {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
        <button key={n} type="button" aria-current={n === current ? 'page' : undefined} onClick={() => onChange(n)} className={cn(cell, n === current ? 'bg-ink text-white' : 'border border-line text-text2 hover:bg-white')}>
          {n}
        </button>
      ))}
      {current < pages && (
        <button type="button" onClick={() => onChange(current + 1)} className={cn(cell, 'border border-line px-3.5 font-sans text-ink hover:bg-white')}>
          下一页 →
        </button>
      )}
    </nav>
  );
}

/** 标签横排：窄屏横向滚动，宽屏自动换行 */
function TagRow({ tags, active, onTag }: { tags: string[]; active?: string; onTag: (t: string) => void }) {
  if (!tags.length) return null;
  return (
    <div className={cn(COL, 'pt-[18px] pb-3')}>
      <div aria-label="按标签筛选" role="group" className="flex flex-wrap gap-2">
        {tags.map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={t === active}
            onClick={() => onTag(t)}
            className={cn(
              'shrink-0 rounded-full border px-2.5 py-[5px] text-[12.5px] transition-colors',
              t === active ? 'border-ink bg-ink text-white' : 'border-[#e7e6e1] bg-white text-[#6b6a64] hover:border-dash hover:text-ink',
            )}
          >
            # {t}
          </button>
        ))}
      </div>
    </div>
  );
}

/** 列表之后：专题 + 关注更新 */
function More({ data }: { data: BlogData }) {
  const card = 'flex flex-col gap-3 rounded-2xl p-6';
  return (
    <aside aria-label="专题与关注更新" className="flex flex-col gap-4">
      {data.series.length > 0 && (
        <section className={cn(card, 'border border-divider bg-white')}>
          <h2 className="text-[15px] font-medium text-ink">专题</h2>
          <ul>
            {data.series.map((s, i) => (
              <li key={s.id} className={cn(i > 0 && 'border-t border-[#f1f0ec]')}>
                <Link to={`/blog/${s.slugs[s.slugs.length - 1]}`} className="group flex items-center gap-3 py-3">
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="text-[14.5px] font-medium text-ink group-hover:text-[#6b4a2a]">{s.title}</span>
                    <span className="truncate text-[13px] text-muted">{s.desc}</span>
                  </span>
                  <span className="font-num text-[12px] font-medium text-muted">{s.slugs.length} 篇</span>
                  <span aria-hidden className="text-faint transition-colors group-hover:text-[#a8733f]">
                    →
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className={cn(card, 'bg-brand-soft sm:flex-row sm:items-center sm:gap-6')}>
        <span className="flex flex-1 flex-col gap-1.5">
          <h2 className="text-[15px] font-medium text-ink">关注更新</h2>
          <p className="text-[13px] leading-[21px] text-text2">新文章与评测结果随版本发布。在 GitHub 上 Watch 仓库的 Releases，发版时会收到通知。</p>
        </span>
        <a href={RELEASES_URL} target="_blank" rel="noreferrer noopener" className={cn(pill.primary, 'shrink-0 self-start px-[18px] py-2 text-[13.5px] sm:self-center')}>
          查看 Releases ↗
        </a>
      </section>
    </aside>
  );
}
