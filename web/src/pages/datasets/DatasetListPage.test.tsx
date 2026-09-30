import { act, fireEvent, screen, within } from '@testing-library/react';

import { db } from '@/mock/db';
import { renderAt } from '@/test/render';

import DatasetListPage from './DatasetListPage';

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  db.reset();
});
afterEach(() => vi.useRealTimers());

const setup = () => renderAt('/datasets', [{ path: '/datasets', element: <DatasetListPage /> }]);

describe('DatasetListPage', () => {
  it('renders cards and filters by search', () => {
    setup();
    expect(screen.getByText('产品知识库')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('搜索知识库...'), { target: { value: '人事' } });
    expect(screen.queryByText('产品知识库')).not.toBeInTheDocument();
    expect(screen.getByText('人事制度库')).toBeInTheDocument();
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
