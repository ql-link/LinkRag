import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Outlet, useLocation } from 'react-router-dom';

import App from './App';

vi.mock('@/layouts/AppLayout', () => ({ AppLayout: () => <Outlet /> }));
vi.mock('@/pages/home/HomePage', () => ({ default: () => <h1>工作台主页</h1> }));
vi.mock('@/pages/landing/LandingPage', () => ({ default: () => <h1>Hero 页</h1> }));

function CurrentPath() {
  return <output data-testid="current-path">{useLocation().pathname}</output>;
}

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe('域名入口按登录态分流', () => {
  it.each(['/', '/welcome'])('未登录访问 %s 展示 Hero 页', async (path) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
        <CurrentPath />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('heading', { name: 'Hero 页' })).toBeInTheDocument();
    expect(screen.getByTestId('current-path')).toHaveTextContent(/^\/$/);
    expect(screen.queryByRole('heading', { name: '工作台主页' })).not.toBeInTheDocument();
  });

  it.each(['/', '/welcome'])('已登录访问 %s 进入工作台主页', async (path) => {
    // 模拟刷新页面前已持久化的登录态，AuthProvider 从缓存恢复用户。
    localStorage.setItem('linkrag.user', JSON.stringify({ username: 'tester', displayName: '测试用户', email: 'tester@example.com' }));
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
        <CurrentPath />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('heading', { name: '工作台主页' })).toBeInTheDocument();
    expect(screen.getByTestId('current-path')).toHaveTextContent(/^\/$/);
    expect(screen.queryByRole('heading', { name: 'Hero 页' })).not.toBeInTheDocument();
  });

  it.each([false, true])('/home 固定展示 Hero 页（已登录：%s）', async (authed) => {
    if (authed) localStorage.setItem('linkrag.user', JSON.stringify({ username: 'tester', displayName: '测试用户', email: 'tester@example.com' }));
    render(
      <MemoryRouter initialEntries={['/home']}>
        <App />
        <CurrentPath />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('heading', { name: 'Hero 页' })).toBeInTheDocument();
    expect(screen.getByTestId('current-path')).toHaveTextContent(/^\/home$/);
    expect(screen.queryByRole('heading', { name: '工作台主页' })).not.toBeInTheDocument();
  });
});
