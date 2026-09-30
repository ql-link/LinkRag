import { ListChecks, PanelRight, Sparkles, GitCompare, Database } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';

import { USE_MOCK } from '@/api/http';
import { PageLoading } from '@/components/ui/Loading';
import { usePageLoad } from '@/lib/usePageLoad';
import { FeatherMark } from '@/components/assistant/FeatherMark';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import {
  defaultChatModel,
  getConversation,
  isBusy,
  lastAssistant,
  recentDatasetIds,
  regenerate,
  roundsOf,
  ensureMessages,
  send,
  setFeedback,
  startConversation,
  startConversationAsync,
  stop,
  updateConversation,
  useChat,
  type AssistantMessage,
  type Conversation,
} from '@/services/chat';
import { fileCount } from '@/services/datasets';
import { modelOptions, useModels } from '@/services/models';
import { useStore } from '@/services/useStore';

import { AssistantAnswer } from './components/AssistantAnswer';
import { Composer } from './components/Composer';
import { SourcePanel } from './components/SourcePanel';

/** 从其他页面带入的初始问题 / 知识库（如「基于此文件提问」「向知识库提问」） */
export interface ChatEntryState {
  question?: string;
  datasetIds?: string[];
  autoSend?: boolean;
}

const PANEL_KEY = 'linkrag.chat.panel';

export default function ChatPage() {
  const { conversationId } = useParams();
  const conversation = useChat((s) => getConversation(conversationId, s));
  // 会话列表已由应用外壳装载完成：找不到即回到新对话
  if (conversationId && !conversation) return <Navigate to="/chat" replace />;
  return conversation ? <ConversationView key={conversation.id} conversation={conversation} /> : <NewChat />;
}

function ChatBar({ title, sub, children }: { title: string; sub: string; children?: React.ReactNode }) {
  return (
    <div className="flex h-14 shrink-0 items-center gap-1.5 border-b border-divider pr-6 pl-8">
      <h1 className="truncate text-[13px] font-medium text-ink">{title}</h1>
      <span className="shrink-0 text-[11.5px] text-muted">· {sub}</span>
      <span className="flex-1" />
      {children}
    </div>
  );
}

/* ---------------- F1 新对话 ---------------- */

const suggestions = [
  { icon: <Sparkles />, title: '总结上传的文档', sub: '提炼要点与结论', prompt: '总结一下最近上传的文档，提炼要点与结论' },
  { icon: <GitCompare />, title: '对比两份资料的差异', sub: '逐项列出不同之处', prompt: '对比两份资料的差异，逐项列出不同之处' },
  { icon: <ListChecks />, title: '从知识库检索要点', sub: '按主题整理片段', prompt: 'Q3 路线图里优先级最高的三项是什么？各自负责人和上线时间？' },
];

function NewChat() {
  const navigate = useNavigate();
  const location = useLocation();
  const entry = (location.state ?? {}) as ChatEntryState;
  const datasets = useStore((s) => s.datasets);
  const [question, setQuestion] = useState(entry.question ?? '');
  const [datasetIds, setDatasetIds] = useState<string[]>(entry.datasetIds ?? []);
  // 未手动选择前跟随「模型配置」中的默认对话模型（真实模式下默认值在装载后才可用）
  const [picked, setPicked] = useState<string>();
  const fallbackModel = useModels(() => defaultChatModel());
  const model = picked ?? fallbackModel;
  const setModel = setPicked;
  const recent = recentDatasetIds().map((id) => datasets.find((d) => d.id === id)!).filter(Boolean);

  const toast = useToast();
  const [starting, setStarting] = useState(false);
  const submit = async (q = question) => {
    if (!q.trim() || !datasetIds.length || starting) return;
    // Mock 模式同步创建（无网络请求）
    if (USE_MOCK) return navigate(`/chat/${startConversation({ question: q, datasetIds, model })}`);
    setStarting(true);
    try {
      const id = await startConversationAsync({ question: q, datasetIds, model });
      navigate(`/chat/${id}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : '创建对话失败', { tone: 'error' });
    } finally {
      setStarting(false);
    }
  };

  // 从搜索等入口带着问题和知识库进入时直接发送
  const sent = useRef(false);
  useEffect(() => {
    if (entry.autoSend && !sent.current && entry.question && entry.datasetIds?.length) {
      sent.current = true;
      void startConversationAsync({ question: entry.question, datasetIds: entry.datasetIds, model }).then((id) => navigate(`/chat/${id}`, { replace: true }));
    }
  }, [entry, model, navigate]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-6 pb-[8vh]">
        <div className="flex w-full max-w-[760px] flex-col items-center">
          <div className="flex items-center gap-5">
            <FeatherMark size={40} />
            <h2 className="font-serif text-[32px] leading-[1.4] font-semibold text-ink">你好，今天想查点什么？</h2>
          </div>
          <p className="mt-2 text-[13px] text-muted">回答只基于所选知识库，每条结论都附带来源片段。</p>
          <div className="h-8" />
          <Composer
            hero
            autoFocus
            value={question}
            onChange={setQuestion}
            onSubmit={() => void submit()}
            placeholder="输入你的问题…"
            datasetIds={datasetIds}
            onDatasets={setDatasetIds}
            model={model}
            onModel={setModel}
          />
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {suggestions.map((s) => (
              <button
                key={s.title}
                type="button"
                onClick={() => (datasetIds.length ? void submit(s.prompt) : setQuestion(s.prompt))}
                className="flex h-7 items-center gap-1.5 rounded-full border border-line bg-white px-3 text-[12px] text-text2 transition-colors hover:border-[#cfcfc9] hover:text-ink [&>svg]:size-3"
              >
                {s.icon}
                {s.title}
              </button>
            ))}
          </div>
          {recent.length > 0 && (
            <div className="mt-9 flex w-full flex-col items-center gap-2.5">
              <p className="text-[11px] text-muted">最近使用的知识库</p>
              <div className="flex flex-wrap justify-center gap-2">
                {recent.map((d) => {
                  const on = datasetIds.includes(d.id);
                  return (
                    <button
                      key={d.id}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setDatasetIds(on ? datasetIds.filter((x) => x !== d.id) : [...datasetIds, d.id])}
                      className={cn('flex items-center gap-[7px] rounded-[8px] border py-[6px] pr-3 pl-2.5 text-[12px] transition-colors', on ? 'border-ink bg-white text-ink' : 'border-transparent bg-soft text-ink hover:bg-active')}
                    >
                      <Database aria-hidden className="size-3 text-text2" />
                      {d.name}
                      <span className="font-num text-[10.5px] font-medium text-muted">{fileCount(d.id)}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------------- F2–F7 对话 ---------------- */

function ConversationView({ conversation: c }: { conversation: Conversation }) {
  const toast = useToast();
  // 真实模式：首次打开会话时加载历史消息（含引用片段正文），全部返回后再展示；新建 / 已加载的会话直接展示
  const fetched = usePageLoad(() => ensureMessages(c.id), [c.id], () => toast('历史消息加载失败', { tone: 'error' }));
  const loaded = USE_MOCK || !!c.loaded || fetched;
  const [draft, setDraft] = useState('');
  const [panel, setPanel] = useState(() => localStorage.getItem(PANEL_KEY) !== 'closed');
  const [activeCite, setActiveCite] = useState<number>();
  const last = lastAssistant(c);
  const busy = isBusy(last);
  const altModel = useModels((s) => [...modelOptions('chat', s).personal, ...modelOptions('chat', s).platform].find((m) => m.name !== c.model)?.name);

  const setPanelOpen = (open: boolean) => {
    setPanel(open);
    localStorage.setItem(PANEL_KEY, open ? 'open' : 'closed');
    if (!open) setActiveCite(undefined);
  };

  const onCite = (n: number) => {
    setActiveCite(n);
    setPanelOpen(true);
  };

  // Esc 停止生成（F4）
  useEffect(() => {
    if (!busy) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented && !document.querySelector('[role="dialog"]')) stop(c.id);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [busy, c.id]);

  // 新消息 / 流式输出时，若用户停留在底部则自动跟随滚动
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const length = c.messages.length;
  const shown = last?.shown ?? 0;
  const status = last?.status;
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [length, shown, status, loaded]);

  const submit = () => {
    if (busy || !draft.trim()) return;
    stick.current = true;
    send(c.id, draft);
    setDraft('');
    setActiveCite(undefined);
  };

  if (!loaded) return <PageLoading label="正在加载对话…" />;

  const panelAnswer = activeCite !== undefined ? ([...c.messages].reverse().find((m) => m.role === 'assistant' && m.chunks.some((x) => x.n === activeCite)) as AssistantMessage | undefined) ?? last : last;

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <ChatBar title={c.title} sub={`${roundsOf(c)} 轮`}>
          <span className="relative">
            <IconButton label={panel ? '收起引用面板' : '展开引用面板'} pressed={panel} onClick={() => setPanelOpen(!panel)}>
              <PanelRight />
            </IconButton>
            {!panel && !!last?.chunks.length && (
              <span aria-hidden className="pointer-events-none absolute top-[3px] right-[3px] min-w-[14px] rounded-[7px] bg-ink px-1 text-center font-num text-[9px] leading-3 font-semibold text-white">
                {last.chunks.length}
              </span>
            )}
          </span>
        </ChatBar>
        <div
          ref={scroller}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
          }}
          className="min-h-0 flex-1 overflow-y-auto px-6"
        >
          <div className="mx-auto flex w-full max-w-[760px] flex-col gap-8 pt-9 pb-10">
            {c.messages.map((m) =>
              m.role === 'user' ? (
                <div key={m.id} className="flex justify-end">
                  <p className="max-w-[80%] rounded-xl bg-[#f4f4f2] px-3.5 py-2.5 text-[13.5px] leading-[22px] whitespace-pre-wrap text-ink">{m.text}</p>
                </div>
              ) : (
                <AssistantAnswer
                  key={m.id}
                  m={m}
                  last={m === last}
                  activeCite={panel && panelAnswer === m ? activeCite : undefined}
                  onCite={onCite}
                  altModel={altModel}
                  onRegenerate={(model) => {
                    stick.current = true;
                    regenerate(c.id, model);
                    if (model) toast(`已切换为 ${model} 重新生成`);
                  }}
                  onFeedback={(v) => {
                    setFeedback(c.id, m.id, v);
                    if (v) toast('感谢反馈');
                  }}
                />
              ),
            )}
          </div>
        </div>
        <div className="shrink-0 px-6 pb-7">
          <div className="mx-auto w-full max-w-[760px]">
            <Composer
              value={draft}
              onChange={setDraft}
              onSubmit={submit}
              placeholder={busy ? '回答生成中… 你可以先输入下一个问题' : '继续提问或补充要求…'}
              datasetIds={c.datasetIds}
              onDatasets={(ids) => updateConversation(c.id, { datasetIds: ids })}
              model={c.model}
              onModel={(model) => {
                updateConversation(c.id, { model });
                toast(`后续提问将使用 ${model}`);
              }}
              busy={busy}
              onStop={() => stop(c.id)}
              note={busy ? <span className="text-[11px] text-muted">按 Esc 停止生成</span> : undefined}
            />
          </div>
        </div>
      </div>
      {panel && <SourcePanel answer={panelAnswer} datasetIds={c.datasetIds} active={activeCite} onSelect={setActiveCite} />}
    </div>
  );
}

function IconButton({ label, pressed, onClick, children }: { label: string; pressed?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      onClick={onClick}
      className={cn('flex size-8 items-center justify-center rounded-[8px] text-text2 transition-colors hover:bg-soft hover:text-ink [&>svg]:size-4', pressed && 'bg-active text-ink hover:bg-active')}
    >
      {children}
    </button>
  );
}
