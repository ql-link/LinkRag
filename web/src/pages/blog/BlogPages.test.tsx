import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import logo from '@/assets/brand/logo-mark.png';
import { renderAt } from '@/test/render';

import BlogListPage from './BlogListPage';
import BlogPostPage from './BlogPostPage';
import { makeBlogData, STATIC_POSTS } from './posts';
import * as blogData from './data';
import { fromMarkdown } from './markdown';

const routes = [
  { path: '/blog', element: <BlogListPage /> },
  { path: '/blog/:slug', element: <BlogPostPage /> },
];

describe('BlogListPage (single column)', () => {
  it('stacks featured card, text-only rows and the series block after the list', async () => {
    renderAt('/blog', routes);
    const featured = await screen.findByRole('region', { name: '头条文章' });
    expect(within(featured).getByRole('link', { name: STATIC_POSTS[0].title })).toBeInTheDocument();

    const list = screen.getByRole('region', { name: '最新文章' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows.length).toBeGreaterThan(0);
    // 列表行不再带缩略封面
    expect(list.querySelector('img, [aria-hidden][style*="background"]')).toBeNull();
    // 专题与关注更新排在列表之后
    const more = screen.getByRole('complementary', { name: '专题与关注更新' });
    expect(list.compareDocumentPosition(more) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('filters by a tag from the tag row', async () => {
    renderAt('/blog', routes);
    const group = await screen.findByRole('group', { name: '按标签筛选' });
    const first = within(group).getAllByRole('button')[0];
    fireEvent.click(first);
    expect(first).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { level: 2, name: /找到 \d+ 篇/ })).toBeInTheDocument();
  });
});

describe('BlogPostPage (single column)', () => {
  const post = STATIC_POSTS.find((p) => p.sections.length > 1)!;

  it('renders the left chapter navigation without the old collapsible card', async () => {
    renderAt(`/blog/${post.slug}`, routes);
    const toc = await screen.findByRole('navigation', { name: '本文目录' });
    expect(within(toc).getAllByRole('link')).toHaveLength(post.sections.filter((s) => s.id !== 'intro').length);
    expect(toc).toHaveClass('sticky');
    expect(screen.queryByRole('button', { name: '收起' })).toBeNull();
    expect(screen.queryByRole('button', { name: '展开' })).toBeNull();
  });

  it('keeps opening text but excludes the generated intro from headings and navigation', async () => {
    const article = fromMarkdown({ slug: 'intro-test', title: '测试文章', summary: '摘要', publishedAt: null, coverPublicUrl: null, contentMarkdown: '开头正文。\n\n## 正式章节\n\n章节正文。' }, '团队');
    const spy = vi.spyOn(blogData, 'useBlog').mockReturnValue({ status: 'ready', data: makeBlogData([article]) });
    try {
      renderAt(`/blog/${article.slug}`, routes);
      expect(screen.getByText('开头正文。')).toBeInTheDocument();
      expect(screen.queryByText('导语')).toBeNull();
      const toc = screen.getByRole('navigation', { name: '本文目录' });
      expect(within(toc).getAllByRole('link')).toHaveLength(1);
      expect(within(toc).getByRole('link')).toHaveTextContent('01正式章节');
      expect(screen.getByRole('heading', { level: 2, name: /正式章节/ })).toHaveTextContent('01正式章节');
    } finally {
      spy.mockRestore();
    }
  });

  it('disables boundary overscroll on the public scroll container', async () => {
    renderAt(`/blog/${post.slug}`, routes);
    await screen.findByRole('navigation', { name: '本文目录' });
    expect(document.getElementById('landing-scroll')).toHaveClass('overscroll-y-none');
  });

  it('opens the floating TOC panel from the 目录 button', async () => {
    renderAt(`/blog/${post.slug}`, routes);
    await screen.findByRole('navigation', { name: '本文目录' });
    fireEvent.click(screen.getByRole('button', { name: /^目录/ }));
    const panel = screen.getByRole('dialog', { name: '本文目录' });
    expect(within(panel).getAllByRole('link')).toHaveLength(post.sections.filter((s) => s.id !== 'intro').length);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '本文目录' })).toBeNull();
  });

  it('uses the project logo for both author slots', async () => {
    renderAt(`/blog/${post.slug}`, routes);
    await screen.findByRole('heading', { level: 1, name: post.title });
    const article = screen.getByRole('article');
    const logos = Array.from(article.querySelectorAll('img')).filter((img) => img.getAttribute('src') === logo);
    expect(logos).toHaveLength(2);
    expect(logos.map((img) => img.getAttribute('width'))).toEqual(['36', '48']);
  });

  it('omits previous/next, figures and report resource cards even on series articles', async () => {
    const seriesPost = STATIC_POSTS.find((p) => p.series && p.figures && p.reportId)!;
    renderAt(`/blog/${seriesPost.slug}`, routes);
    await screen.findByRole('heading', { level: 1, name: seriesPost.title });
    expect(screen.queryByRole('navigation', { name: '同专题文章' })).toBeNull();
    expect(screen.queryByText('上一篇', { exact: false })).toBeNull();
    expect(screen.queryByText('下一篇', { exact: false })).toBeNull();
    expect(screen.queryByText(seriesPost.figures![0].note)).toBeNull();
    expect(screen.queryByText('原始 JSON')).toBeNull();
    const related = screen.getByRole('region', { name: '继续阅读' });
    expect(within(related).getAllByText('阅读 →')).toHaveLength(within(related).getAllByRole('listitem').length);
  });

  it('renders ordinary Markdown blocks and copies the entire code including indentation', async () => {
    const code = 'from pathlib import Path\n\ndef count():\n    return len(list(Path("docs").rglob("*.md")))';
    const article = fromMarkdown({
      slug: 'markdown-test', title: '普通 Markdown', summary: '摘要', publishedAt: null, coverPublicUrl: null,
      contentMarkdown: '开头正文。\n\n## 内容\n\n### 小标题\n\n> 引用文字\n\n- 列表内容\n\n1. 检查内容\n\n| 分类 | 主要内容 |\n| --- | --- |\n| 指南 | **入门说明** |\n\n```python\n' + code + '\n```',
    }, 'LinkRag 团队');
    const spy = vi.spyOn(blogData, 'useBlog').mockReturnValue({ status: 'ready', data: makeBlogData([article]) });
    const writeText = vi.fn().mockResolvedValue(undefined);
    const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    try {
      renderAt(`/blog/${article.slug}`, routes);
      expect(screen.getByRole('heading', { level: 3, name: '小标题' })).toBeInTheDocument();
      expect(screen.getByText('引用文字').closest('blockquote')).toBeInTheDocument();
      expect(screen.getByText('列表内容').closest('ul')).toBeInTheDocument();
      expect(screen.getByText('检查内容').closest('ol')).toBeInTheDocument();
      expect(within(screen.getByRole('table')).getByText('入门说明').tagName).toBe('STRONG');
      fireEvent.click(screen.getByRole('button', { name: /^复制$/ }));
      await waitFor(() => expect(writeText).toHaveBeenCalledWith(code));
      expect(await screen.findByRole('button', { name: /^已复制$/ })).toBeInTheDocument();
    } finally {
      spy.mockRestore();
      if (clipboard) Object.defineProperty(navigator, 'clipboard', clipboard);
      else Reflect.deleteProperty(navigator, 'clipboard');
    }
  });

});
