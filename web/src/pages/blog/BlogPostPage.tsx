import { Check, ChevronDown, Copy, Link2, List as ListIcon, Share2, ThumbsDown, ThumbsUp } from 'lucide-react';
import { Fragment, useEffect, useRef, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';

import logo from '@/assets/brand/logo-mark.png';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { Inline } from '@/lib/inlineMarkdown';
import { FEEDBACK_URL, GITHUB_URL, pill } from '@/pages/landing/shared';
import { PublicShell, SCROLL_ROOT_ID } from '@/pages/landing/SiteChrome';
import { useCopy, useScrollSpy } from '@/pages/research/components';
import { findReport } from '@/pages/research/data';

import { BlogStatus, CategoryLabel } from './components';
import { useBlog } from './data';
import { AUTHOR, CATEGORY_TONE, neighbors, readMinutes, relatedPosts, type BlogData, type Block, type Post } from './posts';

/**
 * 博客文章详情（设计稿「10 博客 · V2 单栏」L12 v2）。
 * 全部区块居中于同一条 720 内容栏：文章头、关键数字、目录卡片、正文、文末、继续阅读。
 * 目录放在正文之前，可折叠；目录卡片滚出视口后，右下角出现「目录」按钮，点开为抽屉。
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
  const ids = post.sections.map((s) => s.id);
  const active = useScrollSpy(ids, SCROLL_ROOT_ID);
  const { series, index, prev, next } = neighbors(data, post);
  const related = relatedPosts(data, post);
  const report = findReport(post.reportId);
  const tocRef = useRef<HTMLElement>(null);
  const tocGone = useScrolledPast(tocRef);

  return (
    <article aria-labelledby="post-title">
      <ReadingProgress />
      {/* 文章头 */}
      <header className={cn(COL, 'flex flex-col gap-[18px] pt-10 pb-8 md:pt-14')}>
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

      {post.figures && (
        <div className={cn(COL, 'pb-10')}>
          <dl className="grid overflow-hidden rounded-2xl border border-divider bg-white sm:grid-cols-3">
            {post.figures.map((f, i) => (
              <div key={f.label} className={cn('flex flex-col gap-2 p-6', i > 0 && 'border-t border-divider sm:border-t-0 sm:border-l')}>
                <dt className="text-[12.5px] font-medium text-[#a8733f]">{f.label}</dt>
                <dd className="font-num text-[34px] leading-tight font-semibold tracking-[-0.02em] text-ink">{f.value}</dd>
                <dd className="text-[12.5px] leading-5 text-text2">{f.note}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className={cn(COL, 'flex flex-col gap-12 pb-16')}>
        {post.sections.length > 1 && <Toc ref={tocRef} post={post} active={active} />}
        {/* 正文：第二节起以细线分隔 */}
        <div className="flex min-w-0 flex-col">
          {post.sections.map((s, i) => (
            <section key={s.id} aria-labelledby={s.id} className={cn('flex flex-col gap-5', i > 0 && 'mt-12 border-t border-divider pt-10')}>
              <h2 id={s.id} className="flex scroll-mt-24 flex-col gap-1.5">
                <span className="font-num text-[13px] font-medium text-[#a8733f]">{String(i + 1).padStart(2, '0')}</span>
                <span className="font-serif text-[23px] leading-[1.45] font-semibold text-ink md:text-[26px]">{s.title}</span>
              </h2>
              {s.blocks.map((b, j) => (
                <BlockView key={j} block={b} />
              ))}
            </section>
          ))}
        </div>
        {report && <Resources post={post} />}
        {post.tags.length > 0 && (
          <p className="flex flex-wrap items-center gap-2">
            <span className="text-[12.5px] font-medium text-muted">标签</span>
            {post.tags.map((t) => (
              <Link key={t} to={`/blog?tag=${encodeURIComponent(t)}`} className="rounded-full border border-line bg-white px-3 py-[5px] text-[12.5px] text-text2 transition-colors hover:border-dash hover:text-ink">
                # {t}
              </Link>
            ))}
          </p>
        )}
      </div>

      {/* 文末 */}
      <div className={cn(COL, 'flex flex-col gap-3 pb-20')}>
        <Helpful slug={post.slug} />
        <div className="flex flex-col gap-4 rounded-2xl bg-soft px-6 py-5 sm:flex-row sm:items-center">
          <img src={logo} alt="" width={48} height={48} className="size-12 shrink-0 object-contain" />
          <span className="flex flex-1 flex-col gap-1">
            <span className="text-[15px] font-medium text-ink">{post.author}</span>
            <span className="text-[13px] leading-5 text-text2">{AUTHOR.bio}</span>
          </span>
          <a href={GITHUB_URL} {...ext} className={cn(pill.secondary, 'gap-1.5 self-start px-3.5 py-[7px] text-[12.5px] sm:self-center')}>
            关注仓库 <span className="text-muted">↗</span>
          </a>
        </div>
        {series && (
          <nav aria-label="同专题文章" className="flex flex-col gap-3">
            <Neighbor dir="prev" post={prev} />
            <Neighbor dir="next" post={next} />
          </nav>
        )}
      </div>

      {related.length > 0 && (
        <section aria-labelledby="read-next" className="bg-[#f4f3ef] pt-14 pb-16">
          <div className={cn(COL, 'flex flex-col gap-5')}>
            <div className="flex items-center justify-between">
              <h2 id="read-next" className="font-serif text-[22px] font-semibold text-ink">
                继续阅读
              </h2>
              <Link to="/blog" className="text-[13.5px] font-medium text-[#a8733f] hover:underline">
                全部文章 →
              </Link>
            </div>
            <ul className="flex flex-col gap-3">
              {related.map((r) => (
                <li key={r.slug}>
                  <Link to={`/blog/${r.slug}`} className="group flex flex-col gap-2 rounded-2xl border border-divider bg-white px-6 py-5 transition-colors hover:border-line">
                    <span className="font-serif text-[18px] leading-[1.5] font-semibold text-ink group-hover:text-[#6b4a2a]">{r.title}</span>
                    <span className="flex items-center gap-2 text-[12.5px]">
                      <CategoryLabel post={r} />
                      <span className="text-faint">·</span>
                      <span className="font-num text-muted">
                        {r.date} · {readMinutes(r)} 分钟
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {post.sections.length > 1 && <TocFab post={post} active={active} visible={tocGone} />}
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
    <div className="mt-1 flex flex-wrap items-center gap-3 border-t border-divider pt-5">
      <img src={logo} alt="" width={40} height={40} className="size-10 shrink-0 object-contain" />
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

/** 目录卡片完全滚出滚动容器顶部后返回 true（用来切换浮动「目录」按钮） */
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

function TocLinks({ post, active, onPick, columns }: { post: Post; active: string; onPick?: () => void; columns?: boolean }) {
  return (
    <ol className={cn('grid gap-x-8', columns && 'sm:grid-cols-2')}>
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
              <span className={cn('text-[14px] leading-[21px]', on && 'font-medium')}>{s.title}</span>
            </a>
          </li>
        );
      })}
    </ol>
  );
}

/** 正文前的目录卡片：两列，可折叠 */
function Toc({ ref, post, active }: { ref: React.Ref<HTMLElement>; post: Post; active: string }) {
  const [open, setOpen] = useState(true);
  return (
    <nav ref={ref} aria-label="本文目录" className="rounded-2xl bg-[#f7f5f0] px-6 py-5">
      <div className="flex items-center justify-between">
        <p className="text-[12.5px] font-medium text-text2">本文目录 · {post.sections.length} 节</p>
        <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex items-center gap-1 text-[12.5px] text-muted hover:text-ink">
          {open ? '收起' : '展开'}
          <ChevronDown aria-hidden className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
        </button>
      </div>
      {open && (
        <div className="pt-2">
          <TocLinks post={post} active={active} columns />
        </div>
      )}
    </nav>
  );
}

/** 滚过目录卡片后出现的浮动按钮；点开为右下角目录面板（窄屏为底部抽屉） */
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
    <div ref={panel} className={cn('fixed right-4 bottom-4 z-30 flex flex-col items-end gap-3 transition-[opacity,transform] duration-200 md:right-8 md:bottom-8', visible ? 'opacity-100' : 'pointer-events-none translate-y-2 opacity-0')}>
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

const prose = 'text-[16px] leading-[30px] text-[#2b2a27] md:text-[17px] md:leading-[32px]';

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
        <blockquote className={cn(prose, 'border-l-[3px] border-[#e4ddd2] pl-5 text-text2')}>
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
                <span aria-hidden className="w-5 shrink-0 text-right font-num text-[#b87a3a]">
                  {n + 1}.
                </span>
              ) : (
                <span aria-hidden className="mt-[13px] size-[5px] shrink-0 rounded-full bg-[#b87a3a] md:mt-[14px]" />
              )}
              <span>
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
        <figure className="flex flex-col gap-2">
          <div className="overflow-x-auto rounded-[14px] border border-divider bg-white">
            <table className="w-full min-w-[480px] text-left text-[14px]">
              <thead className="bg-[#fbfbf9]">
                <tr>
                  {b.head.map((h, i) => (
                    <th key={h} scope="col" className={cn('px-5 py-3 font-medium text-muted', i > 0 && 'w-[130px]')}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r) => (
                  <tr key={r[0]} className="border-t border-[#f1f0ec]">
                    {r.map((c, i) => (
                      <td key={i} className={cn('px-5 py-3', i === 0 ? 'text-ink' : 'font-num font-medium', i > 0 && i === r.length - 1 && /^[+−-]/.test(c) ? 'text-brand' : i > 0 && 'text-ink')}>
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
  const cmds = lines.filter((l) => l.startsWith('$ ')).map((l) => l.slice(2));
  return (
    <div className="overflow-hidden rounded-[14px] bg-[#1f1e1b]">
      <div className="flex items-center px-4 py-2.5">
        <span className="rounded-md bg-[#2c2b27] px-2.5 py-[3px] font-num text-[11.5px] font-medium text-[#c9c8c0]">{lang}</span>
        <span className="flex-1" />
        <button type="button" onClick={() => copy(cmds.join('\n'), '命令已复制')} className="flex items-center gap-1 text-[12px] font-medium text-[#e8d9c3] hover:text-white">
          {copied ? <Check aria-hidden className="size-3" /> : <Copy aria-hidden className="size-3" />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre className="overflow-x-auto px-5 pt-1.5 pb-[18px] font-mono text-[13.5px] leading-[23px]">
        {lines.map((l, i) => (
          <div key={i} className={l.startsWith('#') ? 'text-[#8f8d84]' : 'text-[#ededea]'}>
            {l}
          </div>
        ))}
      </pre>
    </div>
  );
}

/** 本文数据：评测报告 / 原始 JSON / 复现命令 + 数据来源 */
function Resources({ post }: { post: Post }) {
  const r = findReport(post.reportId)!;
  const [copy] = useCopy();
  const tile = 'flex items-center gap-2.5 rounded-xl border border-divider bg-white px-[18px] py-3.5 text-left transition-colors hover:border-line';
  const arrow = 'ml-auto font-num text-[14px] text-[#a8733f]';
  return (
    <div className="flex flex-col gap-3 pt-6">
      <div className="grid gap-3 sm:grid-cols-3">
        <Link to={`/research/${r.id}`} className={tile}>
          <span className="flex flex-col gap-0.5">
            <span className="text-[14px] font-medium text-ink">评测报告</span>
            <span className="font-num text-[12px] text-muted">{r.title.split(' · ')[0]} · 详情页</span>
          </span>
          <span aria-hidden className={arrow}>
            →
          </span>
        </Link>
        {r.rawUrl ? (
          <a href={r.rawUrl} download={`${r.id}.json`} className={tile}>
            <span className="flex flex-col gap-0.5">
              <span className="text-[14px] font-medium text-ink">原始 JSON</span>
              <span className="font-num text-[12px] text-muted">{r.id}.json</span>
            </span>
            <span aria-hidden className={arrow}>
              ↓
            </span>
          </a>
        ) : (
          <button type="button" disabled title="原始结果暂未公开" className={cn(tile, 'cursor-not-allowed hover:border-divider')}>
            <span className="flex flex-col gap-0.5">
              <span className="text-[14px] font-medium text-faint">原始 JSON</span>
              <span className="text-[12px] text-faint">暂未公开</span>
            </span>
          </button>
        )}
        {r.command ? (
          <button type="button" onClick={() => copy(r.command!, '复现命令已复制')} className={tile}>
            <span className="flex flex-col gap-0.5">
              <span className="text-[14px] font-medium text-ink">复现命令</span>
              <span className="text-[12px] text-muted">复制到剪贴板</span>
            </span>
            <Copy aria-hidden className="ml-auto size-3.5 text-[#a8733f]" />
          </button>
        ) : (
          <a href={GITHUB_URL} {...ext} className={tile}>
            <span className="flex flex-col gap-0.5">
              <span className="text-[14px] font-medium text-ink">评测代码</span>
              <span className="text-[12px] text-muted">GitHub 仓库</span>
            </span>
            <span aria-hidden className={arrow}>
              ↗
            </span>
          </a>
        )}
      </div>
      <p className="border-t border-divider pt-4 text-[12.5px] text-muted">
        数据来源　{r.title}
        {r.rawUrl && <> · 原始结果 {r.id}.json</>} · 生成于 {r.date}
      </p>
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

function Neighbor({ dir, post }: { dir: 'prev' | 'next'; post?: Post }) {
  const label = dir === 'prev' ? '← 上一篇' : '下一篇 →';
  const cls = cn('flex flex-col gap-1.5 rounded-2xl border border-divider bg-white px-5 py-[18px]', dir === 'next' && 'sm:items-end sm:text-right');
  if (!post)
    return (
      <div className={cls}>
        <span className="text-[12.5px] text-muted">{label}</span>
        <span className="text-[15px] font-medium text-[#b5b4ac]">{dir === 'next' ? '已是这个专题的最新一篇' : '这是这个专题的第一篇'}</span>
      </div>
    );
  return (
    <Link to={`/blog/${post.slug}`} className={cn(cls, 'group transition-colors hover:border-line')}>
      <span className="text-[12.5px] text-muted">{label}</span>
      <span className="text-[15px] font-medium text-ink group-hover:text-[#6b4a2a]">{post.title}</span>
    </Link>
  );
}
