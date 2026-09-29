import { fireEvent, screen } from '@testing-library/react';

import { renderAt } from '@/test/render';

import AuthPage from './AuthPage';

beforeEach(() => localStorage.clear());

describe('AuthPage register', () => {
  it('shows inline errors on invalid submit (A3)', () => {
    renderAt('/register', [{ path: '/register', element: <AuthPage mode="register" /> }]);
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'abc12345' } });
    fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'abc1234' } });
    fireEvent.click(screen.getByRole('button', { name: /创建账号/ }));
    expect(screen.getByText('两次输入的密码不一致')).toBeInTheDocument();
    expect(screen.getByText('注册失败：请检查表单信息')).toBeInTheDocument();
  });
});
