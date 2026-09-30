import { act, fireEvent, screen, within } from '@testing-library/react';

import { renderAt } from '@/test/render';

import AccountPage from './AccountPage';

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  localStorage.setItem('linkrag.user', JSON.stringify({ username: 'chenmo', displayName: '陈默', email: 'chenmo@example.com', createdAt: '2026-03-12' }));
});
afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
});

const setup = () => renderAt('/account', [{ path: '/account', element: <AccountPage /> }]);

describe('AccountPage', () => {
  it('edits and saves the profile, with validation', async () => {
    setup();
    const form = screen.getByRole('form', { name: '个人资料' });
    const save = within(form).getByRole('button', { name: '保存修改' });
    expect(save).toBeDisabled();
    expect(within(form).getByLabelText('用户名')).toBeDisabled();

    const email = within(form).getByLabelText(/邮箱/);
    fireEvent.change(email, { target: { value: 'bad-email' } });
    expect(within(form).getByRole('alert')).toHaveTextContent('邮箱格式不正确');
    expect(save).toBeDisabled();

    fireEvent.change(email, { target: { value: 'chen@linkrag.dev' } });
    fireEvent.change(within(form).getByLabelText(/显示名称/), { target: { value: '陈默 Chen' } });
    fireEvent.change(within(form).getByLabelText('所属团队'), { target: { value: '平台组' } });
    fireEvent.click(save);
    await act(() => vi.advanceTimersByTimeAsync(500));

    expect(JSON.parse(localStorage.getItem('linkrag.user')!)).toMatchObject({ displayName: '陈默 Chen', email: 'chen@linkrag.dev', team: '平台组' });
    expect(screen.getByText('个人资料已保存')).toBeInTheDocument();
    expect(save).toBeDisabled();
  });

  it('changes the password in a dialog', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: /修改密码/ }));
    const dialog = screen.getByRole('dialog', { name: '修改登录密码' });
    const confirm = within(dialog).getByRole('button', { name: '确认修改' });
    fireEvent.change(within(dialog).getByLabelText(/当前密码/), { target: { value: '123' } });
    fireEvent.change(within(dialog).getByLabelText(/^新密码/), { target: { value: 'linkrag-2026' } });
    fireEvent.change(within(dialog).getByLabelText(/确认新密码/), { target: { value: 'linkrag-2027' } });
    expect(within(dialog).getByRole('alert')).toHaveTextContent('两次输入的密码不一致');
    expect(confirm).toBeDisabled();

    fireEvent.change(within(dialog).getByLabelText(/确认新密码/), { target: { value: 'linkrag-2026' } });
    fireEvent.click(confirm);
    await act(() => vi.advanceTimersByTimeAsync(600));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('当前密码不正确');

    fireEvent.change(within(dialog).getByLabelText(/当前密码/), { target: { value: 'old-password' } });
    fireEvent.click(confirm);
    await act(() => vi.advanceTimersByTimeAsync(600));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('密码已修改')).toBeInTheDocument();
  });
});
