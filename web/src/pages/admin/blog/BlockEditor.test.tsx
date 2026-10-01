import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { BlockEditor } from './BlockEditor';
import { parseDoc, serializeDoc, type EBlock } from './blocks';

function Harness({ initial }: { initial: string }) {
  const [blocks, setBlocks] = useState<EBlock[]>(() => parseDoc(initial).blocks);
  return (
    <>
      <BlockEditor blocks={blocks} onChange={(fn) => setBlocks(fn)} onUpload={() => {}} />
      <pre data-testid="md">{serializeDoc({ frontMatter: null, blocks })}</pre>
      <button type="button">外部</button>
    </>
  );
}

const flush = () => act(() => new Promise((r) => setTimeout(r, 20)));

describe('live-render editor', () => {
  it('renders markdown until the block is clicked, then shows its source', async () => {
    render(<Harness initial={'# 标题\n\n含 **粗体** 的段落'} />);
    expect(screen.getByText('标题')).toBeInTheDocument();
    expect(screen.getByText('粗体').tagName).toBe('STRONG');
    expect(screen.queryByLabelText('Markdown 源码')).toBeNull();

    fireEvent.mouseDown(screen.getByText('粗体'), { button: 0 });
    await flush();
    const area = screen.getByLabelText<HTMLTextAreaElement>('Markdown 源码');
    expect(area.value).toBe('含 **粗体** 的段落');
    // 其余块保持渲染
    expect(screen.getByText('标题').closest('[role="textbox"]')).not.toBeNull();
  });

  it('turns typed "# " into a heading once the block loses focus', async () => {
    render(<Harness initial="待改写" />);
    fireEvent.mouseDown(screen.getByText('待改写', { selector: 'span' }), { button: 0 });
    await flush();
    const area = screen.getByLabelText<HTMLTextAreaElement>('Markdown 源码');
    fireEvent.change(area, { target: { value: '# 1231' } });
    // 编辑中首行语法立即决定块样式
    expect(area.parentElement?.className).toContain('text-[26px]');
    // 焦点真正移出（仅触发 blur 事件时 activeElement 不变，编辑器会视为仍在编辑）
    act(() => screen.getByText('外部').focus());
    await flush();
    expect(screen.queryByLabelText('Markdown 源码')).toBeNull();
    expect(screen.getByText('1231').closest('[role="textbox"]')?.className).toContain('text-[26px]');
    expect(screen.getByTestId('md').textContent).toBe('# 1231\n');
  });

  it('continues lists on Enter and exits on an empty item', async () => {
    render(<Harness initial="- a" />);
    fireEvent.mouseDown(screen.getByText('a', { selector: 'span' }), { button: 0 });
    await flush();
    const area = () => screen.getByLabelText<HTMLTextAreaElement>('Markdown 源码');
    area().setSelectionRange(3, 3);
    fireEvent.keyDown(area(), { key: 'Enter' });
    await flush();
    expect(area().value).toBe('- a\n- ');
    area().setSelectionRange(6, 6);
    fireEvent.keyDown(area(), { key: 'Enter' });
    await flush();
    expect(screen.getByTestId('md').textContent).toBe('- a\n');
    expect(area().value).toBe('');
  });

  it('loads a replacement image after the previous image failed', () => {
    const { rerender } = render(
      <BlockEditor blocks={[{ id: 'image', t: 'img', src: '/missing.png', alt: '图注' }]} onChange={() => {}} onUpload={() => {}} />,
    );
    fireEvent.error(screen.getByRole('img', { name: '图注' }));
    expect(screen.getByText('图片无法加载：')).toBeInTheDocument();

    rerender(
      <BlockEditor blocks={[{ id: 'image', t: 'img', src: '/replacement.png', alt: '图注' }]} onChange={() => {}} onUpload={() => {}} />,
    );
    const replacement = screen.getByRole('img', { name: '图注' });
    expect(replacement).toHaveAttribute('src', '/replacement.png');
    expect(screen.queryByText('图片无法加载：')).toBeNull();
    fireEvent.load(replacement);
    fireEvent.error(replacement);
    expect(screen.getByText('图片无法加载：')).toBeInTheDocument();
  });
});
