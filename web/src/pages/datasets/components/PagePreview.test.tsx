import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Chunk } from '@/mock/chunks';
import { MarkdownBody } from './MarkdownBody';
import { PageCanvas, PreviewPane } from './PagePreview';

const markdown = '# 一级标题\n\n## 二级标题\n\n正文 **加粗** 和 *斜体*、~~删除~~、`inline`。\n\n| 名称 | 数量 |\n| --- | ---: |\n| 数据 | 2 |\n\n- 无序项\n\n1. 有序项\n\n- [x] 已完成\n\n> 引用内容\n\n```ts\nconst value = 1;\n```\n\n[资料](https://example.com)\n\n![图示](https://example.com/image.png)';
const chunk: Chunk = { id: 'chunk-1', index: 1, kind: 'text', section: '章节', page: 1, tokens: 80, text: markdown, overlap: 0 };

describe('document Markdown preview', () => {
  it('renders document structure and inline formats in the default pane, retaining selection', () => {
    const select = vi.fn();
    render(<PageCanvas chunks={[chunk]} page={1} selectedId={chunk.id} onSelect={select} />);
    expect(screen.getByRole('heading', { level: 1, name: '一级标题' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: '二级标题' })).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '名称' })).toBeInTheDocument();
    expect(screen.getByText('加粗').tagName).toBe('STRONG');
    expect(screen.getByText('斜体').tagName).toBe('EM');
    expect(screen.getByText('删除').tagName).toBe('DEL');
    expect(screen.getAllByRole('list')).toHaveLength(3);
    expect(screen.getByRole('checkbox')).toBeChecked();
    expect(screen.getByText('引用内容').closest('blockquote')).not.toBeNull();
    expect(screen.getByText('const value = 1;').closest('pre')).not.toBeNull();
    expect(screen.getByRole('img', { name: '图示' })).toHaveAttribute('src', 'https://example.com/image.png');
    const block = screen.getByRole('button', { name: '选中分块 #1' });
    expect(block).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByText('加粗'));
    fireEvent.keyDown(block, { key: 'Enter' });
    expect(select).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('link', { name: '资料' }));
    expect(select).toHaveBeenCalledTimes(2);
  });

  it('renders the full Markdown tab as rich content', () => {
    render(<PreviewPane page={1} pages={1} onPage={vi.fn()} pageChunks={[chunk]} onSelect={vi.fn()} markdown={markdown} />);
    fireEvent.click(screen.getByRole('tab', { name: '解析结果 Markdown' }));
    expect(screen.getByRole('heading', { name: '一级标题' })).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('preserves HTML table spans and removes scripts, event handlers and unsafe URLs', () => {
    const { container } = render(<MarkdownBody>{'<table><tr><th colspan="2">合并表头</th></tr><tr><td rowspan="2">单元格</td><td>值</td></tr></table>\n\n<script>alert(1)</script><img src="x" onerror="alert(1)" />\n\n[危险](javascript:alert%281%29)'}</MarkdownBody>);
    expect(screen.getByRole('columnheader')).toHaveAttribute('colspan', '2');
    expect(screen.getByText('单元格')).toHaveAttribute('rowspan', '2');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('[onerror]')).toBeNull();
    expect(container.querySelector('a')).not.toHaveAttribute('href', expect.stringContaining('javascript:'));
  });

  it('renders Markdown in table/image chunks without mock metadata and handles empty pages', () => {
    const { rerender } = render(<PageCanvas chunks={[{ ...chunk, kind: 'table' }]} page={1} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
    rerender(<PageCanvas chunks={[{ ...chunk, kind: 'image' }]} page={1} />);
    expect(screen.getByRole('img', { name: '图示' })).toBeInTheDocument();
    rerender(<PageCanvas chunks={[]} page={1} />);
    expect(screen.getByText('当前页暂无正文内容')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
