import { Search, X } from 'lucide-react';
import { useEffect, useMemo, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import logo from '@/assets/brand/logo-mark.png';
import { cn } from '@/lib/cn';
import { PageIntro, pill } from '@/pages/landing/shared';
import { PublicShell, SCROLL_ROOT_ID } from '@/pages/landing/SiteChrome';
import { RELEASES_URL } from '@/pages/research/data';

import { BlogStatus, CategoryLabel, Cover } from './components';
import { useBlog } from './data';
import { allTags, CATEGORIES, postText, readMinutes, type BlogData, type Category, type Post } from './posts';

/**
 * 博客列表（设计稿「10 博客」L11）：刊头 + 分类页签 + 头条 + 文章列表 / 粘性侧栏。
 * 分类、标签、搜索词与页码写在 URL 查询参数里，便于分享与返回。
 */
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
      {featured && current === 1 && <Featured post={featured} />}
      <div className="mx-auto flex max-w-[1440px] flex-col gap-12 px-5 pt-6 pb-24 md:px-[100px] xl:flex-row xl:gap-[60px]">
        <section id="blog-list" aria-labelledby="blog-list-title" className="min-w-0 flex-1 scroll-mt-24">
          <div className="flex items-center gap-3 pb-2">
            <h2 id="blog-list-title" className="font-serif text-[20px] font-semibold text-ink">
              {plain ? '最新文章' : `找到 ${filtered.length} 篇`}
            </h2>
            {tag && <FilterChip label={`标签：${tag}`} onClear={() => update({ tag: undefined })} />}
            {q && <FilterChip label={`搜索：${q}`} onClear={() => update({ q: undefined })} />}
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
        <Sidebar data={data} activeTag={tag} onTag={(t) => update({ tag: t === tag ? undefined : t, c: undefined })} />
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
    <PageIntro
      title="检索这件事，我们做了什么"
      desc={
        <>
          评测复盘、技术笔记和版本更新。文章里的数字都能在
          <Link to="/research" className="text-[#a8733f] hover:underline">
            评测中心
          </Link>
          找到原始结果。
        </>
      }
      aside={
          <form
            role="search"
            onSubmit={(e) => {
              e.preventDefault();
              onSearch(input.current?.value.trim() ?? '');
            }}
            className="flex h-10 w-full items-center gap-2 rounded-full border border-line bg-white px-4 focus-within:border-brand md:w-[260px]"
          >
            <Search aria-hidden className="size-4 text-muted" />
            <input
              ref={input}
              key={q}
              type="search"
              defaultValue={q}
              placeholder="搜索文章"
              aria-label="搜索文章"
              className="min-w-0 flex-1 bg-transparent text-[13.5px] text-ink outline-none placeholder:text-muted [&::-webkit-search-cancel-button]:hidden"
            />
            <kbd className="hidden rounded-[5px] border border-line px-1.5 font-num text-[11px] font-medium text-muted md:block">/</kbd>
          </form>
      }
    />
  );
}

function Tabs({ posts, category, onChange }: { posts: Post[]; category?: Category; onChange: (c?: Category) => void }) {
  const items: { c?: Category; label: string; n: number }[] = [{ label: '全部', n: posts.length }, ...CATEGORIES.map((c) => ({ c, label: c, n: posts.filter((p) => p.category === c).length }))];
  return (
    <div className="mx-auto max-w-[1440px] px-5 md:px-[100px]">
      <div role="tablist" aria-label="文章分类" className="flex gap-7 overflow-x-auto overflow-y-hidden border-b border-divider [scrollbar-width:none]">
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
      <img src={logo} alt="" width={28} height={28} className="size-7 shrink-0 object-contain" />
      <span className="text-[13.5px] font-medium text-ink">{post.author}</span>
      <span className="text-[13px] text-muted">· {readMinutes(post)} 分钟阅读</span>
    </span>
  );
}

function Featured({ post }: { post: Post }) {
  return (
    <section aria-label="头条文章" className="mx-auto grid max-w-[1440px] items-center gap-8 px-5 py-8 md:px-[100px] md:py-12 lg:grid-cols-[540fr_640fr] lg:gap-[60px]">
      <div className="flex flex-col gap-4">
        <p className="flex items-center gap-2.5 text-[13px]">
          <span className="rounded-full bg-brand px-[9px] py-[3px] text-[11.5px] font-medium text-white">最新</span>
          <CategoryLabel post={post} />
          <span className="text-faint">·</span>
          <time dateTime={post.date} className="font-num text-muted">
            {post.date}
          </time>
        </p>
        <h2 className="font-serif text-[clamp(26px,3vw,34px)] leading-[1.4] font-semibold text-ink">
          <Link to={`/blog/${post.slug}`} className="hover:text-[#6b4a2a]">
            {post.title}
          </Link>
        </h2>
        <p className="text-[15.5px] leading-[27px] text-text2">{post.lead}</p>
        <Byline post={post} />
        <Link to={`/blog/${post.slug}`} className={cn(pill.secondary, 'mt-2 gap-2 self-start px-[18px] py-2.5 text-[14px]')}>
          阅读全文
          <span aria-hidden className="text-muted">
            →
          </span>
        </Link>
      </div>
      <Link to={`/blog/${post.slug}`} tabIndex={-1} aria-hidden className="hidden lg:block">
        <Cover post={post} size="lg" className="aspect-[640/380] transition-transform duration-300 hover:scale-[1.01]" />
      </Link>
    </section>
  );
}

function Row({ post }: { post: Post }) {
  const [y, m, d] = post.date.split('-');
  return (
    <li className="border-b border-divider">
      <Link to={`/blog/${post.slug}`} className="group flex gap-5 py-7 md:gap-7">
        <span className="hidden w-[72px] shrink-0 flex-col gap-0.5 sm:flex">
          <span className="font-num text-[26px] leading-tight font-semibold text-ink">{d}</span>
          <span className="font-num text-[12px] font-medium text-muted">
            {y}.{m}
          </span>
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-2.5">
          <span className="flex items-center gap-2 text-[12.5px]">
            <CategoryLabel post={post} />
            <span className="text-faint">·</span>
            <span className="text-muted">{readMinutes(post)} 分钟</span>
            <time dateTime={post.date} className="font-num text-muted sm:hidden">
              · {post.date}
            </time>
          </span>
          <span className="font-serif text-[19px] leading-[1.5] font-semibold text-ink group-hover:text-[#6b4a2a] md:text-[21px]">{post.title}</span>
          <span className="line-clamp-2 text-[14px] leading-[23px] text-text2">{post.lead}</span>
          <span className="text-[12.5px] text-muted">{post.author}</span>
        </span>
        <Cover post={post} size="sm" className="hidden h-32 w-48 shrink-0 md:flex" />
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

/**
 * 侧栏：列表比侧栏长时保持吸顶（top 96）；视口矮于侧栏时取消吸顶，避免底部被裁掉。
 * 1280 以下改为单栏，侧栏排在列表之后。
 */
function Sidebar({ data, activeTag, onTag }: { data: BlogData; activeTag?: string; onTag: (t: string) => void }) {
  const tags = allTags(data.posts);
  const card = 'flex flex-col gap-2.5 rounded-[18px] p-[18px]';
  return (
    <aside aria-label="专题与标签" className="w-full shrink-0 xl:w-[360px]">
      <div className="grid gap-4 md:grid-cols-2 xl:sticky xl:top-24 xl:flex xl:flex-col [@media(max-height:720px)]:static">
        {data.series.length > 0 && (
        <section className={cn(card, 'border border-divider bg-white')}>
          <h2 className="text-[14.5px] font-medium text-ink">专题</h2>
          <ul>
            {data.series.map((s, i) => (
              <li key={s.id} className={cn(i > 0 && 'border-t border-[#f1f0ec]')}>
                <Link to={`/blog/${s.slugs[s.slugs.length - 1]}`} className="group flex items-center gap-3 py-[9px]">
                  <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
                    <span className="text-[14px] font-medium text-ink group-hover:text-[#6b4a2a]">{s.title}</span>
                    <span className="truncate text-[12.5px] text-muted">{s.desc}</span>
                  </span>
                  <span className="font-num text-[12px] font-medium text-muted">{s.slugs.length} 篇</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
        )}
        <section className={cn(card, 'bg-brand-soft')}>
          <h2 className="text-[14.5px] font-medium text-ink">关注更新</h2>
          <p className="text-[13px] leading-[21px] text-text2">新文章与评测结果随版本发布。在 GitHub 上 Watch 仓库的 Releases，发版时会收到通知。</p>
          <a href={RELEASES_URL} target="_blank" rel="noreferrer noopener" className={cn(pill.primary, 'mt-1 self-start px-[18px] py-2 text-[13.5px]')}>
            查看 Releases ↗
          </a>
        </section>
        {tags.length > 0 && (
        <section className={cn(card, 'border border-divider bg-white')}>
          <h2 className="text-[14.5px] font-medium text-ink">标签</h2>
          <div className="flex flex-wrap gap-2">
            {tags.map((t) => (
              <button
                key={t}
                type="button"
                aria-pressed={t === activeTag}
                onClick={() => {
                  onTag(t);
                  document.getElementById(SCROLL_ROOT_ID)?.scrollTo({ top: 0 });
                }}
                className={cn('rounded-full px-[11px] py-[5px] text-[12.5px] transition-colors', t === activeTag ? 'bg-ink text-white' : 'bg-soft text-text2 hover:bg-active')}
              >
                {t}
              </button>
            ))}
          </div>
        </section>
        )}
      </div>
    </aside>
  );
}
