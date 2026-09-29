import { act, fireEvent, screen, within } from '@testing-library/react';

import { ConversationList } from '@/layouts/ConversationList';
import { chatStore } from '@/services/chat';
import { renderAt } from '@/test/render';

import ChatPage from './ChatPage';

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  chatStore.reset();
  localStorage.clear();
});
afterEach(() => vi.useRealTimers());

const page = (
  <div>
    <ConversationList />
    <ChatPage />
  </div>
);
const setup = (path = '/chat') =>
  renderAt(path, [
    { path: '/chat', element: page },
    { path: '/chat/:conversationId', element: page },
  ]);

describe('ChatPage', () => {
  it('requires a dataset, then streams an answer with thinking steps and citations (F1 → F4 → F2)', async () => {
    setup();
    const input = screen.getByRole('textbox', { name: '输入问题' });
    fireEvent.change(input, { target: { value: 'Q3 路线图里优先级最高的三项是什么？各自负责人和上线时间？' } });
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /产品知识库/, pressed: false }));
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(screen.getByRole('list', { name: '思考过程' })).toHaveTextContent('理解问题进行中');
    expect(screen.getByRole('button', { name: '停止生成' })).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(1200));
    expect(screen.getByRole('list', { name: '思考过程' })).toHaveTextContent('召回 8 个片段');

    await act(() => vi.advanceTimersByTimeAsync(6000));
    const answer = screen.getByRole('article', { name: 'LinkRag 的回答' });
    expect(answer).toHaveTextContent('对话引用溯源');
    expect(within(answer).getByRole('button', { name: /已思考/ })).toHaveAttribute('aria-expanded', 'false');
    // 新对话出现在侧栏顶部
    expect(within(screen.getByRole('navigation', { name: '对话' })).getAllByRole('listitem')[0]).toHaveTextContent('Q3 路线图里优先级最高的三项是');

    // F6 点击片段查看原文
    fireEvent.click(within(answer).getByRole('button', { name: '查看片段 3 原文' }));
    const panel = screen.getByRole('complementary', { name: '引用来源' });
    expect(panel).toHaveTextContent('Q3 路线图规划.docx');
    expect(panel).toHaveTextContent('引用于回答第 2 项');

    // 收起 / 展开面板
    fireEvent.click(screen.getByRole('button', { name: '收起引用面板' }));
    expect(screen.queryByRole('complementary', { name: '引用来源' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '展开引用面板' }));
    expect(screen.getByRole('complementary', { name: '引用来源' })).toHaveTextContent('召回片段');
  });

  it('stops generation with Esc and shows the failure card with retry (F4 / F7)', async () => {
    setup('/chat/c_01');
    const input = screen.getByRole('textbox', { name: '输入问题' });
    fireEvent.change(input, { target: { value: '第 1 项的技术风险有哪些？' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await act(() => vi.advanceTimersByTimeAsync(1600));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getAllByRole('article').at(-1)).toHaveTextContent('已停止生成');

    fireEvent.change(input, { target: { value: '模拟失败' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await act(() => vi.advanceTimersByTimeAsync(1600));
    expect(screen.getByRole('alert')).toHaveTextContent('回答生成失败');
    fireEvent.click(screen.getByRole('button', { name: '换个模型重试' }));
    await act(() => vi.advanceTimersByTimeAsync(6000));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getAllByRole('article').at(-1)).toHaveTextContent(/检索 \d 个片段 · [\d.]+s/);
  });

  it('pins, renames inline and deletes conversations from the sidebar (F5)', async () => {
    setup('/chat/c_01');
    const nav = screen.getByRole('navigation', { name: '对话' });
    fireEvent.click(within(nav).getByRole('button', { name: '竞品分析报告对比 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '置顶' }));
    expect(within(nav).getByText('置顶')).toBeInTheDocument();
    expect(within(nav).getAllByRole('listitem')[0]).toHaveTextContent('竞品分析报告对比');

    fireEvent.click(within(nav).getByRole('button', { name: 'API 鉴权流程说明 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /重命名/ }));
    const input = within(nav).getByRole('textbox', { name: '对话标题' });
    fireEvent.change(input, { target: { value: 'API 鉴权流程 v2' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await act(() => vi.advanceTimersByTimeAsync(200));
    expect(within(nav).getByRole('link', { name: 'API 鉴权流程 v2' })).toBeInTheDocument();

    fireEvent.click(within(nav).getByRole('button', { name: 'Q3 产品路线图要点 的更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: '删除对话' }));
    expect(screen.getByRole('dialog', { name: '删除对话「Q3 产品路线图要点」？' })).toHaveTextContent('1 轮问答');
    fireEvent.click(screen.getByRole('button', { name: '删除对话' }));
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(within(nav).queryByText('Q3 产品路线图要点')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '你好，今天想查点什么？' })).toBeInTheDocument();
  });
});
