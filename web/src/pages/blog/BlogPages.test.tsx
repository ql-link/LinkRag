import { fireEvent, screen, within } from '@testing-library/react';

import { renderAt } from '@/test/render';

import BlogListPage from './BlogListPage';
import BlogPostPage from './BlogPostPage';
import { STATIC_POSTS } from './posts';

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

  it('renders an inline, collapsible table of contents before the body', async () => {
    renderAt(`/blog/${post.slug}`, routes);
    const toc = await screen.findByRole('navigation', { name: '本文目录' });
    expect(within(toc).getByText(`本文目录 · ${post.sections.length} 节`)).toBeInTheDocument();
    expect(within(toc).getAllByRole('link')).toHaveLength(post.sections.length);

    const firstH2 = screen.getByRole('heading', { level: 2, name: new RegExp(post.sections[0].title) });
    expect(toc.compareDocumentPosition(firstH2) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(within(toc).getByRole('button', { name: '收起' }));
    expect(within(toc).queryAllByRole('link')).toHaveLength(0);
    fireEvent.click(within(toc).getByRole('button', { name: '展开' }));
    expect(within(toc).getAllByRole('link')).toHaveLength(post.sections.length);
  });

  it('opens the floating TOC panel from the 目录 button', async () => {
    renderAt(`/blog/${post.slug}`, routes);
    await screen.findByRole('navigation', { name: '本文目录' });
    fireEvent.click(screen.getByRole('button', { name: /^目录/ }));
    const panel = screen.getByRole('dialog', { name: '本文目录' });
    expect(within(panel).getAllByRole('link')).toHaveLength(post.sections.length);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '本文目录' })).toBeNull();
  });
});
