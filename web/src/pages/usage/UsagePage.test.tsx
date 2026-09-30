import { act, fireEvent, screen, within } from '@testing-library/react';

import { renderAt } from '@/test/render';

import UsagePage from './UsagePage';

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

const setup = async (path = '/usage') => {
  renderAt(path, [{ path: '/usage', element: <UsagePage /> }]);
  await act(() => vi.advanceTimersByTimeAsync(300));
};

describe('UsagePage', () => {
  it('shows the E1 overview for the last 7 days', async () => {
    await setup();
    const summary = screen.getByRole('region', { name: '用量汇总' });
    expect(summary).toHaveTextContent('1,284,562');
    expect(summary).toHaveTextContent('18.4% 环比');
    expect(screen.getByRole('button', { name: '统计周期：2026-09-21 — 09-27' })).toBeInTheDocument();
    const rows = within(screen.getByRole('table', { name: '最近调用' })).getAllByRole('row');
    expect(rows).toHaveLength(6);
    expect(rows[3]).toHaveTextContent('请求超时');
    fireEvent.click(screen.getByRole('button', { name: /加载更多/ }));
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(26);
  });

  it('switches period via presets and typed 8-digit dates (E2)', async () => {
    await setup();
    fireEvent.click(screen.getByRole('button', { name: /统计周期/ }));
    fireEvent.click(screen.getByRole('option', { name: '上个月' }));
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(screen.getByRole('button', { name: '统计周期：2026-08-01 — 08-31' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /统计周期/ }));
    fireEvent.change(screen.getByPlaceholderText('20260901-20260915'), { target: { value: '20260901-20260915' } });
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(screen.getByRole('button', { name: '统计周期：2026-09-01 — 09-15' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('picks a custom range on the calendar', async () => {
    await setup();
    fireEvent.click(screen.getByRole('button', { name: /统计周期/ }));
    fireEvent.click(screen.getByRole('gridcell', { name: '2026-09-10' }));
    fireEvent.click(screen.getByRole('gridcell', { name: '2026-09-03' }));
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(screen.getByRole('button', { name: '统计周期：2026-09-03 — 09-10' })).toBeInTheDocument();
  });

  it('shows the empty state for a period without data (E3)', async () => {
    await setup('/usage?from=20260601&to=20260607');
    expect(screen.getByText('当前周期暂无用量数据')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '检查模型配置' })).toBeInTheDocument();
  });
});
