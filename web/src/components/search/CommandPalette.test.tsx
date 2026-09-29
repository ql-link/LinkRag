import { fireEvent, screen } from '@testing-library/react';
import { useLocation } from 'react-router-dom';

import { SearchProvider } from '@/contexts/SearchContext';
import { db } from '@/mock/db';
import { renderAt } from '@/test/render';

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

beforeEach(() => {
  db.reset();
  localStorage.clear();
});

const setup = () =>
  renderAt('/', [
    { path: '/', element: <SearchProvider><Where /></SearchProvider> },
    { path: '/datasets/:id/files/:fileId', element: <Where /> },
  ]);

describe('CommandPalette (B4)', () => {
  it('opens with ⌘K, filters by keyword and opens the best match with Enter', () => {
    setup();
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    const input = screen.getByRole('combobox', { name: '搜索文件、对话与知识库' });
    fireEvent.change(input, { target: { value: '竞品' } });
    expect(screen.getByRole('group', { name: '最佳匹配' })).toHaveTextContent('竞品分析报告.pdf');
    expect(screen.getByText('查看全部 7 个结果')).toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByTestId('where')).toHaveTextContent('/datasets/ds_7f3a91c2/files/f_004');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows recent searches, recent visits and actions in a single column when empty (B6)', () => {
    setup();
    fireEvent.keyDown(document, { key: 'k', metaKey: true });
    expect(screen.getByRole('group', { name: '最近搜索' })).toHaveTextContent('定价方案');
    expect(screen.getByRole('group', { name: '最近访问' })).toHaveTextContent('产品需求文档_v3.2.pdf');
    expect(screen.getByRole('group', { name: '快捷操作' })).toHaveTextContent('检查模型配置');
    expect(screen.queryByText('提示')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('option', { name: /定价方案/ }));
    expect(screen.getByRole('combobox')).toHaveValue('定价方案');
    expect(screen.getByText('预览')).toBeInTheDocument();
  });

  it('moves selection with arrow keys and switches scope with Tab', () => {
    setup();
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: '竞品' } });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(screen.getByRole('option', { selected: true })).toHaveTextContent('竞品功能对照表.docx');
    fireEvent.keyDown(input, { key: 'Tab' });
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('文件');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
