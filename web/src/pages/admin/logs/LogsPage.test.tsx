import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { renderAt } from '@/test/render';

import LogsPage from './LogsPage';

const setup = (path = '/admin/logs') => renderAt(path, [{ path: '/admin/logs', element: <LogsPage /> }]);

describe('LogsPage', () => {
  it('lists logs, opens detail, and filters by trace_id', async () => {
    setup();
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.length).toBeGreaterThan(0);

    fireEvent.click(rows[0]);
    const panel = await screen.findByRole('complementary', { name: '日志详情' });
    expect(within(panel).getByText('logger')).toBeInTheDocument();

    const traceBtn = within(rows[0]).getByTitle('按此 trace_id 追踪');
    const traceId = traceBtn.textContent!;
    fireEvent.click(traceBtn);
    await waitFor(() => expect(screen.getByText('链路追踪')).toBeInTheDocument());
    expect(screen.getByLabelText('trace_id')).toHaveValue(traceId);
  });

  it('applies deep-link level filter and shows empty state', async () => {
    setup('/admin/logs?level=FATAL&range=2h');
    expect(await screen.findByText('没有匹配的日志')).toBeInTheDocument();
    expect(screen.getByText('1 项')).toBeInTheDocument();
  });
});
