import { act, fireEvent, screen, within } from '@testing-library/react';

import { modelStore } from '@/services/models';
import { renderAt } from '@/test/render';

import ModelsPage from './ModelsPage';

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  modelStore.reset();
});
afterEach(() => vi.useRealTimers());

const setup = () => renderAt('/models', [{ path: '/models', element: <ModelsPage /> }]);

describe('ModelsPage', () => {
  it('switches the default chat model from the dropdown (D4)', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: '默认对话模型：DeepSeek-V3' }));
    const list = screen.getByRole('listbox', { name: '对话模型' });
    expect(screen.queryByText(/预览：/)).not.toBeInTheDocument();
    const option = within(list).getByRole('option', { name: /Qwen-Max/ });
    fireEvent.mouseEnter(option);
    expect(screen.getByText('预览：Qwen-Max')).toBeInTheDocument();
    fireEvent.mouseLeave(option);
    expect(screen.queryByText(/预览：/)).not.toBeInTheDocument();
    fireEvent.mouseEnter(option);
    fireEvent.click(within(list).getByRole('option', { name: /Qwen-Max/ }));
    await act(() => vi.advanceTimersByTimeAsync(200));
    expect(screen.getByRole('button', { name: '默认对话模型：Qwen-Max' })).toBeInTheDocument();
  });

  it('closes the dropdown when clicking elsewhere, and vector defaults are switchable', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: '默认对话模型：DeepSeek-V3' }));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole('heading', { name: '模型配置' }));
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '默认稠密向量模型：bge-m3' }));
    fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: /bge-large-zh-v1.5/ }));
    await act(() => vi.advanceTimersByTimeAsync(200));
    expect(screen.getByRole('button', { name: '默认稠密向量模型：bge-large-zh-v1.5' })).toBeInTheDocument();
  });

  it('collapses provider groups by default and expands on search', () => {
    setup();
    const deepseek = screen.getByRole('region', { name: 'DeepSeek' });
    expect(within(deepseek).queryByText('DeepSeek-R1')).not.toBeVisible();
    fireEvent.click(within(deepseek).getByRole('button', { name: '展开 DeepSeek 的模型' }));
    expect(within(deepseek).getByText('DeepSeek-R1')).toBeVisible();
    fireEvent.change(screen.getByPlaceholderText('搜索厂商、模型或能力'), { target: { value: 'qwen-long' } });
    expect(screen.getByText('qwen-long')).toBeVisible();
  });

  it('adds a provider through pick → key → test → save (D2 → D3)', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: '添加厂商' }));
    fireEvent.click(screen.getByRole('radio', { name: /智谱 AI/ }));
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    expect(screen.getByRole('heading', { name: '配置 智谱 AI' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/API Key/), { target: { value: 'sk-6f2c1234567890abcdefa91e' } });
    fireEvent.click(screen.getByRole('button', { name: '测试连接' }));
    await act(() => vi.advanceTimersByTimeAsync(800));
    expect(screen.getByRole('status')).toHaveTextContent('连接成功');
    fireEvent.click(screen.getByRole('button', { name: '保存并启用' }));
    await act(() => vi.advanceTimersByTimeAsync(800));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    const region = screen.getByRole('region', { name: '智谱 AI' });
    expect(region).toHaveTextContent('4 个模型 · 3 个已启用');
    fireEvent.click(within(region).getByRole('button', { name: '展开 智谱 AI 的模型' }));
    expect(within(region).getByText('GLM-4-Plus')).toBeVisible();
  });

  it('rejects an invalid key with an inline error', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: '添加厂商' }));
    fireEvent.click(screen.getByRole('radio', { name: /月之暗面/ }));
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    fireEvent.change(screen.getByLabelText(/API Key/), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: '保存并启用' }));
    await act(() => vi.advanceTimersByTimeAsync(800));
    expect(screen.getByRole('alert')).toHaveTextContent('密钥无效');
  });
});
