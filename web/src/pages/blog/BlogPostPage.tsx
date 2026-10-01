import { Check, Copy, Link2, List as ListIcon, Share2, ThumbsDown, ThumbsUp } from 'lucide-react';
import { Fragment, useEffect, useRef, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';

import logo from '@/assets/brand/logo-mark.png';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { Inline } from '@/lib/inlineMarkdown';
import { FEEDBACK_URL, GITHUB_URL, pill } from '@/pages/landing/shared';
import { PublicShell, SCROLL_ROOT_ID } from '@/pages/landing/SiteChrome';
import { useCopy, useScrollSpy } from '@/pages/research/components';

import { BlogStatus, CategoryLabel } from './components';
import { useBlog } from './data';
import { AUTHOR, CATEGORY_TONE, neighbors, readMinutes, relatedPosts, type BlogData, type Block, type Post } from './posts';

/**
 * 博客文章详情：正文保持 720 居中，宽屏目录放在左侧留白，窄屏使用浮动目录。
 */
const ext = { target: '_blank', rel: 'noreferrer noopener' } as const;
/** 内容栏：720 居中，左右留白 20 / 24 */
const COL = 'mx-auto w-full max-w-[768px] px-5 md:px-6';

export default function BlogPostPage() {
  const { slug } = useParams();
  const state = useBlog();
  if (state.status !== 'ready') return <PublicShell><BlogStatus state={state} /></PublicShell>;
  const post = state.data.posts.find((p) => p.slug === slug);
  if (!post) return <Navigate to="/blog" replace />;
  return (
    <PublicShell>
      <Article key={post.slug} post={post} data={state.data} />
    </PublicShell>
  );
}

function Article({ post, data }: { post: Post; data: BlogData }) {
  const chapters = post.sections.filter((s) => s.id !== 'intro');
  const tocPost = { ...post, sections: chapters };
  const ids = chapters.map((s) => s.id);
  const active = useScrollSpy(ids, SCROLL_ROOT_ID);
  const { series, index } = neighbors(data, post);
  const related = relatedPosts(data, post);
  const headerRef = useRef<HTMLElement>(null);
  const headerGone = useScrolledPast(headerRef);

  return (
    <article aria-labelledby="post-title" className="relative">
      {chapters.length > 0 && <Toc post={tocPost} active={active} />}
      <ReadingProgress />
      {/* 文章头 */}
      <header ref={headerRef} className={cn(COL, 'flex flex-col gap-[18px] pt-10 pb-8 md:pt-14')}>
        <p className="flex flex-wrap items-center gap-2.5 text-[13px]">
          <Link to="/blog" className="text-muted hover:text-ink">
            ← 博客
          </Link>
          <span className="text-faint">/</span>
          <span style={{ color: CATEGORY_TONE[post.category].fg, backgroundColor: CATEGORY_TONE[post.category].bg }} className="rounded-full px-2.5 py-[3px] text-[12.5px] font-medium">
            {series ? series.title : post.category}
          </span>
          {series && (
            <span className="text-muted">
              第 {index + 1} 篇，共 {series.slugs.length} 篇
            </span>
          )}
        </p>
        <h1 id="post-title" className="font-serif text-[clamp(28px,4vw,40px)] leading-[1.36] font-semibold tracking-[-0.01em] text-balance text-ink">
          {post.title}
        </h1>
        <p className="text-[17px] leading-[30px] text-[#6b6a64] md:text-[18px] md:leading-[31px]">{post.lead}</p>
        <Byline post={post} />
      </header>

      <div className={cn(COL, 'flex flex-col gap-10 pt-6 pb-16')}>
        <div className="flex min-w-0 flex-col gap-10">
          {post.sections.map((s) => (
            <section key={s.id} aria-labelledby={s.id === 'intro' ? undefined : s.id} className="flex min-w-0 flex-col gap-5">
              {s.id !== 'intro' && <h2 id={s.id} className="flex scroll-mt-24 flex-col gap-1.5">
                <span className="font-num text-[13px] font-medium text-[#a8733f]">{String(chapters.findIndex((chapter) => chapter.id === s.id) + 1).padStart(2, '0')}</span>
                <span className="font-serif text-[23px] leading-[1.45] font-semibold text-ink md:text-[26px]">{s.title}</span>
              </h2>}
              {s.blocks.map((b, j) => (
                <BlockView key={j} block={b} />
              ))}
            </section>
          ))}
        </div>
        {post.tags.length > 0 && (
          <p className="flex flex-wrap items-center gap-2">
            <span className="text-[12.5px] font-medium text-muted">标签</span>
            {post.tags.map((t) => (
              <Link key={t} to={`/blog?tag=${encodeURIComponent(t)}`} className="rounded-full bg-soft px-[11px] py-[5px] text-[12.5px] text-text2 transition-colors hover:bg-line hover:text-ink">
                {t}
              </Link>
            ))}
          </p>
        )}
      </div>

      {/* 文末 */}
      <div className={cn(COL, 'flex flex-col gap-3 pt-6 pb-20')}>
        <Helpful slug={post.slug} />
        <div className="flex flex-col gap-4 rounded-2xl bg-soft px-6 py-5 sm:flex-row sm:items-center">
          <img src={logo} alt="" width={48} height={48} className="size-12 shrink-0 object-contain" />
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="text-[15px] font-medium text-ink">{post.author}</span>
            <span className="text-[13px] leading-5 text-text2">{AUTHOR.bio}</span>
          </span>
          <a href={GITHUB_URL} {...ext} className={cn(pill.secondary, 'shrink-0 gap-1.5 self-start whitespace-nowrap px-3.5 py-[7px] text-[12.5px] sm:self-center')}>
            关注仓库 <span className="text-muted">↗</span>
          </a>
        </div>
      </div>

      {related.length > 0 && (
        <section aria-labelledby="read-next" className="bg-[#f4f3ef] pt-12 pb-14">
          <div className={cn(COL, 'flex flex-col gap-6')}>
            <div className="flex items-center justify-between">
              <h2 id="read-next" className="font-serif text-[22px] font-semibold text-ink">
                继续阅读
              </h2>
              <Link to="/blog" className="text-[13.5px] font-medium text-[#a8733f] hover:underline">
                全部文章 →
              </Link>
            </div>
            <ul className="flex flex-col gap-3.5">
              {related.map((r) => (
                <li key={r.slug}>
                  <Link to={`/blog/${r.slug}`} className="group flex min-w-0 flex-col gap-2.5 rounded-2xl border border-[#e8e7e2] bg-white p-6 transition-colors hover:border-line">
                    <span className="flex items-center justify-between gap-3 text-[12.5px]">
                      <span className="flex items-center gap-2">
                        <span aria-hidden className="size-2 rounded-[2px]" style={{ backgroundColor: CATEGORY_TONE[r.category].fg }} />
                        <CategoryLabel post={r} />
                      </span>
                      <span className="shrink-0 font-medium text-brand">阅读 →</span>
                    </span>
                    <span className="font-serif text-[19px] leading-[29px] font-semibold text-ink group-hover:text-[#6b4a2a]">{r.title}</span>
                    <span className="font-num text-[12.5px] leading-5 text-[#8b8a82]">{r.date} · {readMinutes(r)} 分钟</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {chapters.length > 0 && <TocFab post={tocPost} active={active} visible={headerGone} />}
    </article>
  );
}

/** 顶栏下方 3px 阅读进度 */
function ReadingProgress() {
  const [p, setP] = useState(0);
  useEffect(() => {
    const root = document.getElementById(SCROLL_ROOT_ID);
    if (!root) return;
    const on = () => {
      const max = root.scrollHeight - root.clientHeight;
      setP(max > 0 ? root.scrollTop / max : 0);
    };
    on();
    root.addEventListener('scroll', on, { passive: true });
    return () => root.removeEventListener('scroll', on);
  }, []);
  return (
    <div aria-hidden className="sticky top-[60px] z-20 h-[3px] bg-divider md:top-[72px]">
      <div style={{ transform: `scaleX(${p})` }} className="h-full origin-left bg-brand" />
    </div>
  );
}

function Byline({ post }: { post: Post }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const url = typeof window === 'undefined' ? '' : window.location.href;
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      toast('复制失败，请手动复制地址栏链接', { tone: 'error' });
      return;
    }
    setCopied(true);
    toast('链接已复制', { tone: 'success' });
    setTimeout(() => setCopied(false), 1600);
  };
  const share = async () => {
    if (navigator.share) {
      try {
        await navigator.share({ title: post.title, text: post.lead, url });
      } catch {
        // 用户取消分享
      }
    } else copyLink();
  };
  const btn = cn(pill.secondary, 'gap-1.5 px-3.5 py-[7px] text-[12.5px]');
  return (
    <div className="mt-1 flex flex-wrap items-center gap-3 border-y border-divider py-6">
      <img src={logo} alt="" width={36} height={36} className="size-9 shrink-0 object-contain" />
      <span className="flex flex-col gap-[3px]">
        <span className="text-[14.5px] font-medium text-ink">{post.author}</span>
        <span className="font-num text-[12.5px] text-muted">
          <time dateTime={post.date}>{post.date}</time> · {readMinutes(post)} 分钟阅读
          {post.updated && <> · 更新于 {post.updated.slice(5)}</>}
        </span>
      </span>
      <span className="flex-1" />
      <span className="flex gap-2">
        <button type="button" onClick={copyLink} className={btn}>
          复制链接 {copied ? <Check aria-hidden className="size-3 text-muted" /> : <Link2 aria-hidden className="size-3 text-muted" />}
        </button>
        <button type="button" onClick={share} className={btn}>
          分享 <Share2 aria-hidden className="size-3 text-muted" />
        </button>
      </span>
    </div>
  );
}

/** 文章头完全滚出滚动容器顶部后返回 true（用来切换浮动「目录」按钮） */
function useScrolledPast(ref: React.RefObject<HTMLElement | null>) {
  const [past, setPast] = useState(false);
  useEffect(() => {
    const root = document.getElementById(SCROLL_ROOT_ID);
    const el = ref.current;
    if (!root || !el) return;
    const on = () => setPast(el.getBoundingClientRect().bottom < root.getBoundingClientRect().top + 72);
    on();
    root.addEventListener('scroll', on, { passive: true });
    return () => root.removeEventListener('scroll', on);
  }, [ref]);
  return past;
}

function TocLinks({ post, active, onPick }: { post: Post; active: string; onPick?: () => void }) {
  return (
    <ol className="grid">
      {post.sections.map((s, i) => {
        const on = active === s.id;
        return (
          <li key={s.id}>
            <a
              href={`#${s.id}`}
              onClick={onPick}
              aria-current={on ? 'location' : undefined}
              className={cn('group flex items-baseline gap-2.5 py-2 transition-colors', on ? 'text-[#9c6a3a]' : 'text-text2 hover:text-ink')}
            >
              <span className={cn('font-num text-[11.5px] font-medium', on ? 'text-brand' : 'text-[#b5b4ac]')}>{String(i + 1).padStart(2, '0')}</span>
              <span className="text-[14px] leading-[21px] font-medium">{s.title}</span>
            </a>
          </li>
        );
      })}
    </ol>
  );
}

/** 左侧目录使用正文外的留白，不改变正文居中位置。 */
function Toc({ post, active }: { post: Post; active: string }) {
  return (
    <div className="pointer-events-none absolute top-0 bottom-0 left-[calc(50%-640px)] hidden w-[220px] pt-14 xl:block">
      <nav aria-label="本文目录" className="pointer-events-auto sticky top-28 max-h-[calc(100dvh-144px)] overflow-y-auto overscroll-y-contain border-l border-divider pl-5 pr-2">
        <p className="mb-3 text-[12.5px] font-medium text-muted">本文目录</p>
        <TocLinks post={post} active={active} />
      </nav>
    </div>
  );
}

/** 窄屏滚过文章头后出现目录按钮。 */
function TocFab({ post, active, visible }: { post: Post; active: string; visible: boolean }) {
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const i = Math.max(0, post.sections.findIndex((s) => s.id === active));
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    const onDown = (e: MouseEvent) => panel.current && !panel.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open]);
  useEffect(() => {
    if (!visible) setOpen(false);
  }, [visible]);
  return (
    <div ref={panel} className={cn('fixed right-4 bottom-4 z-30 flex flex-col items-end gap-3 transition-[opacity,transform] duration-200 md:right-8 md:bottom-8 xl:hidden', visible ? 'opacity-100' : 'pointer-events-none translate-y-2 opacity-0')}>
      {open && (
        <div role="dialog" aria-label="本文目录" className="max-h-[min(70dvh,560px)] w-[min(calc(100vw-32px),360px)] overflow-y-auto rounded-2xl border border-divider bg-white px-5 py-4 shadow-[0_12px_40px_-12px_rgba(0,0,0,0.18)]">
          <div className="flex items-center justify-between pb-1">
            <p className="text-[12.5px] font-medium text-text2">本文目录</p>
            <button type="button" onClick={() => document.getElementById(SCROLL_ROOT_ID)?.scrollTo({ top: 0 })} className="text-[12.5px] text-muted hover:text-ink">
              回到顶部 ↑
            </button>
          </div>
          <TocLinks post={post} active={active} onPick={() => setOpen(false)} />
        </div>
      )}
      <button
        type="button"
        aria-expanded={open}
        tabIndex={visible ? 0 : -1}
        onClick={() => setOpen((v) => !v)}
        className="flex max-w-[calc(100vw-32px)] items-center gap-2 rounded-full border border-line bg-white py-2.5 pr-4 pl-3.5 text-[13px] font-medium text-ink shadow-[0_4px_16px_rgba(0,0,0,0.08)] hover:border-dash"
      >
        <ListIcon aria-hidden className="size-4 text-muted" />
        目录
        <span className="truncate font-normal text-muted">
          · <span className="font-num">{String(i + 1).padStart(2, '0')}</span> {post.sections[i]?.title}
        </span>
      </button>
    </div>
  );
}

const prose = 'text-[16px] leading-[30px] text-[#33322e] [overflow-wrap:anywhere] md:text-[17px] md:leading-[31px]';

function BlockView({ block: b }: { block: Block }) {
  switch (b.t) {
    case 'p':
      return (
        <p className={prose}>
          <Inline text={b.text} />
        </p>
      );
    case 'h': {
      const Tag = `h${Math.min(6, Math.max(3, b.level))}` as 'h3';
      return (
        <Tag className={cn('pt-2 font-semibold text-ink', b.level === 3 ? 'text-[19px] md:text-[20px]' : b.level === 4 ? 'text-[17px]' : 'text-[16px]')}>
          <Inline text={b.text} />
        </Tag>
      );
    }
    case 'quote':
      return (
        <blockquote className={cn(prose, 'border-l-[3px] border-[#d4c1a7] py-1 pl-4 text-text2')}>
          {b.text.split('\n').map((l, i) => (
            <Fragment key={i}>
              {i > 0 && <br />}
              <Inline text={l} />
            </Fragment>
          ))}
        </blockquote>
      );
    case 'hr':
      return <hr className="my-2 border-divider" />;
    case 'list': {
      const List = b.ordered ? 'ol' : 'ul';
      return (
        <List className="flex flex-col gap-2">
          {b.items.map((it, n) => (
            <li key={n} className={cn(prose, 'flex gap-3')}>
              {b.ordered ? (
                <span aria-hidden className="w-5 shrink-0 text-right font-num text-[#33322e]">
                  {n + 1}.
                </span>
              ) : (
                <span aria-hidden className="mt-[13px] size-[5px] shrink-0 rounded-full bg-[#33322e] md:mt-[14px]" />
              )}
              <span className="min-w-0">
                <Inline text={it} />
              </span>
            </li>
          ))}
        </List>
      );
    }
    case 'setup':
      return (
        <dl className="overflow-hidden rounded-[14px] border border-divider bg-white">
          {b.rows.map(([k, v], i) => (
            <div key={k} className={cn('flex flex-col gap-1 px-5 py-[13px] sm:flex-row sm:gap-4', i > 0 && 'border-t border-[#f1f0ec]')}>
              <dt className="w-24 shrink-0 text-[14px] text-muted">{k}</dt>
              <dd className="text-[15px] text-ink">{v}</dd>
            </div>
          ))}
        </dl>
      );
    case 'bars':
      return <Bars block={b} />;
    case 'table':
      return (
        <figure className="flex min-w-0 flex-col gap-2">
          <div className="overflow-x-auto rounded-[14px] border border-divider bg-white">
            <table className="w-full min-w-[480px] text-left text-[14px] leading-6 text-[#54544f]">
              <thead className="bg-[#fbfbf9]">
                <tr>
                  {b.head.map((h) => (
                    <th key={h} scope="col" className="px-5 py-3 font-medium">
                      <Inline text={h} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r) => (
                  <tr key={r[0]} className="border-t border-[#f1f0ec]">
                    {r.map((c, i) => (
                      <td key={i} className="px-5 py-3">
                        <Inline text={c} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {b.caption && <figcaption className="text-[12.5px] text-muted">{b.caption}</figcaption>}
        </figure>
      );
    case 'callout':
      return (
        <aside className="flex flex-col gap-2 rounded-[14px] bg-brand-soft px-6 py-5 sm:flex-row sm:gap-4">
          <span className="shrink-0 pt-1 text-[13px] font-medium text-[#a8733f]">{b.label}</span>
          <p className="text-[16px] leading-[29px] text-ink md:text-[16.5px]">
            <Inline text={b.text} />
          </p>
        </aside>
      );
    case 'code':
      return <CodeBlock lang={b.lang} lines={b.lines} />;
    case 'img':
      return (
        <figure className="flex flex-col gap-2">
          <img src={b.src} alt={b.alt} loading="lazy" className="w-full rounded-[14px] border border-divider bg-white" />
          {b.alt && <figcaption className="text-[12.5px] text-muted">{b.alt}</figcaption>}
        </figure>
      );
  }
}

function Bars({ block: b }: { block: Extract<Block, { t: 'bars' }> }) {
  const max = 180;
  return (
    <figure className="flex flex-col gap-5 rounded-2xl border border-divider bg-white p-6">
      <div className="flex gap-[18px] text-[12.5px] text-text2">
        {b.legend.map((l, i) => (
          <span key={l} className="flex items-center gap-1.5">
            <span aria-hidden className={cn('size-2.5 rounded-[2px]', i ? 'bg-[#b87a3a]' : 'bg-[#d8d4ca]')} />
            {l}
          </span>
        ))}
      </div>
      <div role="img" aria-label={b.groups.map((g) => `${g.label}：${b.legend[0]} ${g.values[0]}，${b.legend[1]} ${g.values[1]}`).join('；')} className="flex justify-center gap-10 sm:gap-[140px]">
        {b.groups.map((g) => (
          <div key={g.label} className="flex flex-col items-center gap-3">
            <div className="flex items-end gap-2.5" style={{ height: max + 21 }}>
              {g.values.map((v, i) => (
                <div key={i} className="flex w-14 flex-col items-center gap-1.5 sm:w-[72px]">
                  <span className={cn('font-num text-[12.5px]', i ? 'font-semibold text-ink' : 'font-medium text-muted')}>{v.toFixed(4)}</span>
                  <span style={{ height: v * max * 0.99 + 2 }} className={cn('w-full rounded-t-[3px]', i ? 'bg-[#b87a3a]' : 'bg-[#d8d4ca]')} />
                </div>
              ))}
            </div>
            <span className="text-center text-[13.5px] font-medium text-ink">{g.label}</span>
          </div>
        ))}
      </div>
      <figcaption className="text-[12.5px] text-muted">{b.caption}</figcaption>
    </figure>
  );
}

function CodeBlock({ lang, lines }: { lang: string; lines: string[] }) {
  const [copy, copied] = useCopy();
  return (
    <div className="min-w-0 overflow-hidden rounded-[14px] border border-[#e8e7e2] bg-[#f7f6f2]">
      <div className="flex items-center px-4 py-2.5">
        <span className="rounded-md bg-[#eeede7] px-2.5 py-[3px] font-num text-[11.5px] font-medium text-[#6b6a64]">{lang}</span>
        <span className="flex-1" />
        <button type="button" onClick={() => copy(lines.join('\n'), '代码已复制')} className="flex items-center gap-1 text-[12px] font-medium text-brand hover:text-[#6b4a2a]">
          {copied ? <Check aria-hidden className="size-3" /> : <Copy aria-hidden className="size-3" />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre className="overflow-x-auto px-5 pt-1.5 pb-[18px] font-mono text-[13.5px] leading-[23px]">
        {lines.map((l, i) => (
          <div key={i} className={l.startsWith('#') ? 'text-[#77766e]' : 'text-[#2b2a27]'}>
            {l}
          </div>
        ))}
      </pre>
    </div>
  );
}

const VOTE_KEY = (slug: string) => `linkrag.blog.vote.${slug}`;

function Helpful({ slug }: { slug: string }) {
  const toast = useToast();
  const [vote, setVote] = useState(() => localStorage.getItem(VOTE_KEY(slug)));
  const cast = (v: 'up' | 'down') => {
    setVote(v);
    localStorage.setItem(VOTE_KEY(slug), v);
    toast(v === 'up' ? '感谢反馈' : '感谢反馈，欢迎告诉我们哪里不够清楚', { tone: 'success' });
  };
  const btn = (on: boolean) => cn(pill.secondary, 'gap-1.5 px-3.5 py-[7px] text-[12.5px]', on && 'border-brand bg-brand-soft');
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-divider bg-white px-6 py-[18px] sm:flex-row sm:items-center">
      <span className="flex flex-1 flex-col gap-1">
        <span className="text-[15px] font-medium text-ink">这篇文章对你有帮助吗？</span>
        <Link to={`${FEEDBACK_URL}?from=${encodeURIComponent(`/blog/${slug}`)}`} className="text-[13px] text-[#a8733f] hover:underline">
          发现数据或表述有误？提交反馈 →
        </Link>
      </span>
      <span className="flex gap-2">
        <button type="button" aria-pressed={vote === 'up'} onClick={() => cast('up')} className={btn(vote === 'up')}>
          有帮助 <ThumbsUp aria-hidden className="size-3 text-muted" />
        </button>
        <button type="button" aria-pressed={vote === 'down'} onClick={() => cast('down')} className={btn(vote === 'down')}>
          还不够 <ThumbsDown aria-hidden className="size-3 text-muted" />
        </button>
      </span>
    </div>
  );
}
