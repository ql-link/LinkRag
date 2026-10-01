import { act, fireEvent, screen, within } from '@testing-library/react';

import { db } from '@/mock/db';
import { renderAt } from '@/test/render';

import DatasetListPage from './DatasetListPage';

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  db.reset();
});
afterEach(() => vi.useRealTimers());

const setup = () => renderAt('/datasets', [
  { path: '/datasets', element: <DatasetListPage /> },
  { path: '/datasets/:id', element: <div>知识库详情</div> },
]);

describe('DatasetListPage', () => {
  it('renders cards and filters by search', () => {
    setup();
    expect(screen.getByText('产品知识库')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('搜索知识库...'), { target: { value: '人事' } });
    expect(screen.queryByText('产品知识库')).not.toBeInTheDocument();
    expect(screen.getByText('人事制度库')).toBeInTheDocument();
  });

  it.each([
    { label: 'IME candidate confirmation', isComposing: true, keyCode: 13 },
    { label: 'IME confirmation after compositionend', isComposing: false, keyCode: 229 },
    { label: 'ordinary Enter', isComposing: false, keyCode: 13 },
  ])('requires explicit creation after $label in the name field', async ({ isComposing, keyCode }) => {
    setup();
    const count = db.state.datasets.length;
    fireEvent.click(screen.getByRole('button', { name: '新建知识库' }));
    const dialog = screen.getByRole('dialog');
    const name = within(dialog).getByLabelText(/名称/);
    if (isComposing || keyCode === 229) fireEvent.compositionStart(name);
    fireEvent.change(name, { target: { value: '输入法知识库' } });
    if (keyCode === 229) fireEvent.compositionEnd(name);

    // jsdom 不执行回车的默认表单提交；验证事件被取消，并模拟未取消时的浏览器提交。
    const uncancelled = fireEvent.keyDown(name, { key: 'Enter', code: 'Enter', keyCode, isComposing });
    await act(async () => {
      if (uncancelled) fireEvent.submit(name.closest('form')!);
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(uncancelled).toBe(false);
    expect(db.state.datasets).toHaveLength(count);
    expect(dialog).toBeInTheDocument();
    expect(name).toHaveValue('输入法知识库');
    if (isComposing) fireEvent.compositionEnd(name);

    const description = within(dialog).getByLabelText('描述');
    expect(fireEvent.keyDown(description, { key: 'Enter' })).toBe(true);
    fireEvent.change(description, { target: { value: '第一行\n第二行' } });
    const create = within(dialog).getByRole('button', { name: '创建' });
    expect(fireEvent.keyDown(create, { key: 'Enter' })).toBe(true);
    await act(async () => {
      fireEvent.click(create);
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(db.state.datasets).toHaveLength(count + 1);
    expect(db.state.datasets.find((d) => d.name === '输入法知识库')?.description).toBe('第一行\n第二行');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('disables a dataset through the menu and confirm dialog (C10→C12→C13)', async () => {
    setup();
    fireEvent.click(screen.getByLabelText('产品知识库 更多操作'));
    fireEvent.click(screen.getByRole('menuitem', { name: /停用知识库/ }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('停用「产品知识库」？')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(within(dialog).getByRole('button', { name: /停用知识库/ }));
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(db.state.datasets[0].status).toBe('disabled');
    expect(screen.getByText('已停用')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '撤销' })).toBeInTheDocument();
  });

  it('requires typing the name before deleting (C14)', async () => {
    setup();
    fireEvent.click(screen.getByLabelText('产品知识库 更多操作'));
    fireEvent.click(screen.getByRole('menuitem', { name: /删除知识库/ }));
    const dialog = screen.getByRole('dialog');
    const confirm = within(dialog).getByRole('button', { name: /永久删除/ });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/以确认/), { target: { value: '产品知识库' } });
    expect(confirm).toBeEnabled();
    await act(async () => {
      fireEvent.click(confirm);
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(db.state.datasets.some((d) => d.name === '产品知识库')).toBe(false);
  });
});
