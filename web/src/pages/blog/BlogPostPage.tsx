import { Check, Copy, Link2, Share2, ThumbsDown, ThumbsUp } from 'lucide-react';
import { Fragment, useEffect, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';

import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { Inline } from '@/lib/inlineMarkdown';
import { FEEDBACK_URL, GITHUB_URL, pill } from '@/pages/landing/shared';
import { PublicShell, SCROLL_ROOT_ID } from '@/pages/landing/SiteChrome';
import { useCopy, useScrollSpy } from '@/pages/research/components';
import { findReport } from '@/pages/research/data';

import { BlogStatus, CategoryLabel } from './components';
import { useBlog } from './data';
import { AUTHOR, neighbors, readMinutes, relatedPosts, type BlogData, type Block, type Post } from './posts';

/**
 * 博客文章详情（设计稿「10 博客」L12）。
 * 统一栅格：左侧目录 200 + 间距 64 + 正文 800，标题、关键数字、正文、文末、继续阅读都对齐同一正文栏；
 * 1024 以下隐藏目录，正文单栏。
 */
const ext = { target: '_blank', rel: 'noreferrer noopener' } as const;
/** 页面容器：内容宽 1064（左右各留 40），与正文区同一坐标系 */
const COL = 'mx-auto w-full max-w-[1144px] px-5 md:px-10';
const TEXT = 'max-w-[800px]';
/** 目录以外的区块：桌面左侧让出目录 264（200 + 64），与正文栏左缘对齐 */
const ALIGN = 'max-w-[800px] lg:ml-[264px]';

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

  return (
    <article aria-labelledby="post-title">
      <ReadingProgress />
      {/* 文章头 */}
      <header className={cn(COL, 'pt-8 pb-8 md:pt-12')}>
        <div className={cn(ALIGN, 'flex flex-col gap-4')}>
          <p className="flex flex-wrap items-center gap-2 text-[13px]">
            <Link to="/blog" className="text-muted hover:text-ink">
              ← 博客
            </Link>
            <span className="text-faint">/</span>
            {series ? <span className="font-medium text-[#a8733f]">{series.title}</span> : <CategoryLabel post={post} />}
            {series && (
              <span className="text-muted">
                · 第 {index + 1} 篇，共 {series.slugs.length} 篇
              </span>
            )}
          </p>
          <h1 id="post-title" className="font-serif text-[clamp(28px,4vw,44px)] leading-[1.36] font-semibold tracking-[-0.01em] text-ink">
            {post.title}
          </h1>
          <p className="text-[17px] leading-[30px] text-text2 md:text-[19px] md:leading-[32px]">{post.lead}</p>
          <Byline post={post} />
        </div>
      </header>

      {post.figures && (
        <div className={cn(COL, 'pb-12')}>
          <dl className={cn(ALIGN, 'grid overflow-hidden rounded-[20px] bg-brand-soft sm:grid-cols-3')}>
            {post.figures.map((f, i) => (
              <div key={f.label} className={cn('flex flex-col gap-2 px-6 py-[22px]', i > 0 && 'border-t border-[#e8d9c3] sm:border-t-0 sm:border-l')}>
                <dt className="text-[12.5px] font-medium text-[#a8733f]">{f.label}</dt>
                <dd className="font-num text-[36px] leading-tight font-semibold tracking-[-0.02em] text-ink">{f.value}</dd>
                <dd className="text-[12.5px] text-text2">{f.note}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {/* 正文：左侧粘性目录 + 800 正文 */}
      <div className={cn(COL, 'flex gap-16 pb-16')}>
        <Toc post={post} active={active} />
        <div className={cn(TEXT, 'flex min-w-0 flex-1 flex-col gap-[22px]')}>
          {post.sections.map((s, i) => (
            <section key={s.id} aria-labelledby={s.id} className="flex flex-col gap-[22px]">
              <h2 id={s.id} className="flex scroll-mt-24 flex-col gap-1.5 pt-4">
                <span className="font-num text-[13px] font-medium text-[#a8733f]">{String(i + 1).padStart(2, '0')}</span>
                <span className="font-serif text-[24px] font-semibold text-ink md:text-[27px]">{s.title}</span>
              </h2>
              {s.blocks.map((b, j) => (
                <BlockView key={j} block={b} />
              ))}
            </section>
          ))}
          {report && <Resources post={post} />}
          <p className="flex flex-wrap items-center gap-2 pt-2">
            <span className="text-[12.5px] font-medium text-muted">标签</span>
            {post.tags.map((t) => (
              <Link key={t} to={`/blog?tag=${encodeURIComponent(t)}`} className="rounded-full bg-soft px-[11px] py-[5px] text-[12.5px] text-text2 hover:bg-active">
                {t}
              </Link>
            ))}
          </p>
        </div>
      </div>

      {/* 文末 */}
      <div className={cn(COL, 'pb-20')}>
        <div className={cn(ALIGN, 'flex flex-col gap-4')}>
          <Helpful slug={post.slug} />
          <div className="flex flex-col gap-4 rounded-2xl bg-soft px-6 py-[18px] sm:flex-row sm:items-center">
            <span aria-hidden className="size-12 shrink-0 rounded-full bg-[#e8d9c3]" />
            <span className="flex flex-1 flex-col gap-1">
              <span className="text-[15px] font-medium text-ink">{post.author}</span>
              <span className="text-[13px] leading-5 text-text2">{AUTHOR.bio}</span>
            </span>
            <a href={GITHUB_URL} {...ext} className={cn(pill.secondary, 'gap-1.5 self-start px-3.5 py-[7px] text-[12.5px] sm:self-center')}>
              关注仓库 <span className="text-muted">↗</span>
            </a>
          </div>
          {series && (
            <nav aria-label="同专题文章" className="grid gap-4 sm:grid-cols-2">
              <Neighbor dir="prev" post={prev} />
              <Neighbor dir="next" post={next} />
            </nav>
          )}
        </div>
      </div>

      {related.length > 0 && (
        <section aria-labelledby="read-next" className="bg-soft pt-12 pb-[72px]">
          <div className={COL}>
            <div className={cn(ALIGN, 'flex flex-col gap-5')}>
              <div className="flex items-center justify-between">
                <h2 id="read-next" className="font-serif text-[22px] font-semibold text-ink">
                  继续阅读
                </h2>
                <Link to="/blog" className="text-[13.5px] font-medium text-[#a8733f] hover:underline">
                  全部文章 →
                </Link>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {related.map((r) => (
                  <Link key={r.slug} to={`/blog/${r.slug}`} className="group flex flex-col gap-2.5 rounded-2xl border border-divider bg-white px-[22px] pt-5 pb-[22px] transition-colors hover:border-line">
                    <CategoryLabel post={r} className="text-[12.5px]" />
                    <span className="font-serif text-[18px] leading-[1.5] font-semibold text-ink group-hover:text-[#6b4a2a]">{r.title}</span>
                    <span className="font-num text-[12px] text-muted">
                      {r.date} · {readMinutes(r)} 分钟
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}
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
      <span aria-hidden className="size-10 rounded-full bg-[#e8d9c3]" />
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

function Toc({ post, active }: { post: Post; active: string }) {
  return (
    <aside className="hidden w-[200px] shrink-0 lg:block">
      <nav aria-label="本文目录" className="sticky top-24 flex flex-col [@media(max-height:560px)]:static">
        <p className="pb-2.5 text-[12px] font-medium text-muted">本文目录</p>
        {post.sections.map((s, i) => {
          const on = active === s.id;
          return (
            <a
              key={s.id}
              href={`#${s.id}`}
              aria-current={on ? 'location' : undefined}
              className={cn('flex items-baseline gap-2.5 border-l-2 py-[7px] pl-3.5 transition-colors', on ? 'border-brand' : 'border-divider hover:border-line')}
            >
              <span className={cn('font-num text-[11.5px] font-medium', on ? 'text-brand' : 'text-[#b5b4ac]')}>{String(i + 1).padStart(2, '0')}</span>
              <span className={cn('text-[13.5px]', on ? 'font-medium text-ink' : 'text-text2 hover:text-ink')}>{s.title}</span>
            </a>
          );
        })}
        <button type="button" onClick={() => document.getElementById(SCROLL_ROOT_ID)?.scrollTo({ top: 0 })} className="self-start pt-4 pl-3.5 text-[12.5px] text-muted hover:text-ink">
          回到顶部 ↑
        </button>
      </nav>
    </aside>
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
