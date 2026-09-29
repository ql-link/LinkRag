import { AlertTriangle, Check, ChevronDown, Copy, RefreshCw, Sparkles, ThumbsUp } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { FeatherMark } from '@/components/assistant/FeatherMark';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { revealBlocks, type AnswerBlock, type AssistantMessage, type ThinkingStep } from '@/services/chat';

const stepTitle: Record<ThinkingStep['key'], string> = { understand: '理解问题', retrieve: '检索知识库', generate: '生成回答' };

/** 进行中每 100ms 刷新一次计时 */
function useElapsed(m: AssistantMessage) {
  const running = m.status === 'thinking' || m.status === 'streaming';
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [running]);
  return running ? Math.max(0, (now - m.startedAt) / 1000) : (m.totalElapsed ?? m.thinkingElapsed ?? 0);
}

/**
 * F4 思考过程：时间线展开「理解 → 检索 → 生成」。进行中节点呼吸脉冲、说明文字流光扫过；
 * 回答完成后自动折叠为「已思考 Ns」，可手动展开。
 */
function Thinking({ m, onCite }: { m: AssistantMessage; onCite: (n: number) => void }) {
  const running = m.status === 'thinking' || m.status === 'streaming';
  const [open, setOpen] = useState(running);
  // 生成结束后自动收起
  useEffect(() => {
    if (!running) setOpen(false);
    else setOpen(true);
  }, [running]);
  const elapsed = useElapsed(m);
  const thinking = m.status === 'thinking';
  const label = thinking ? '正在思考' : m.status === 'streaming' ? '正在生成' : m.status === 'stopped' ? '已停止' : m.status === 'error' ? '生成中断' : '已思考';
  const kept = m.chunks.slice(0, 3);

  return (
    <div className="flex flex-col">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex h-6 items-center gap-2 self-start rounded-md pr-1.5 text-left hover:bg-soft">
        <Sparkles aria-hidden className={cn('size-3.5', running ? 'text-ink' : 'text-muted')} />
        <span className={cn('text-[12.5px]', running ? 'font-medium text-ink' : 'text-text2', running && 'text-shimmer')}>{label}</span>
        {/* 历史轮次（真实模式）没有耗时记录：不展示 0.0s */}
        {(running || m.totalElapsed !== undefined || m.thinkingElapsed !== undefined) && (
          <span className="font-num text-[11.5px] font-medium text-muted">{elapsed.toFixed(1)}s</span>
        )}
        <ChevronDown aria-hidden className={cn('size-3 text-muted transition-transform', open && 'rotate-180')} />
      </button>
      <div className={cn('grid transition-[grid-template-rows] duration-300 ease-out', open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
        <ol aria-label="思考过程" className="overflow-hidden pl-0.5">
          <div className="h-2.5" />
          {m.steps.map((s, i) => {
            const last = i === m.steps.length - 1;
            return (
              <li key={s.key} className={cn('flex gap-3', s.state !== 'pending' && 'animate-rise-in')}>
                <div aria-hidden className="flex flex-col items-center pt-[3px]">
                  {s.state === 'done' ? (
                    <span className="flex size-3 items-center justify-center rounded-full bg-green/12 text-green">
                      <Check className="size-2" strokeWidth={3.5} />
                    </span>
                  ) : s.state === 'active' ? (
                    <span className="flex size-3 animate-pulse-ring items-center justify-center rounded-full bg-ink/10">
                      <span className="size-1.5 rounded-full bg-ink" />
                    </span>
                  ) : (
                    <span className="size-3 rounded-full border border-dash bg-white" />
                  )}
                  {!last && <span className={cn('mt-1 w-px flex-1 transition-colors duration-500', s.state === 'done' ? 'bg-green/30' : 'bg-line')} />}
                </div>
                <div className={cn('flex min-w-0 flex-1 flex-col gap-1', !last && 'pb-3.5')}>
                  <span className="flex items-center gap-2">
                    <span className={cn('text-[12.5px]', s.state === 'active' ? 'font-medium text-ink' : s.state === 'done' ? 'text-text2' : 'text-faint')}>{stepTitle[s.key]}</span>
                    {s.elapsed !== undefined && <span className="font-num text-[11px] font-medium text-faint">{s.elapsed.toFixed(1)}s</span>}
                    <span className="sr-only">{s.state === 'done' ? '已完成' : s.state === 'active' ? '进行中' : '未开始'}</span>
                  </span>
                  {s.state === 'active' ? (
                    <span className="text-shimmer text-[11.5px] text-muted">{s.key === 'understand' ? '正在分析问题意图…' : s.key === 'retrieve' ? '正在检索所选知识库…' : '正在组织答案…'}</span>
                  ) : (
                    s.detail && <span className="text-[11.5px] text-muted">{s.detail}</span>
                  )}
                  {s.key === 'retrieve' && s.state === 'done' && kept.length > 0 && (
                    <span className="flex flex-wrap gap-1.5 pt-1">
                      {kept.map((c, j) => (
                        <button
                          key={c.n}
                          type="button"
                          onClick={() => onCite(c.n)}
                          style={{ animationDelay: `${j * 60}ms` }}
                          className="animate-rise-in rounded-[6px] border border-line bg-soft px-2 py-[3px] font-num text-[10.5px] font-medium text-text2 hover:border-ink hover:text-ink"
                        >
                          片段 {c.n}
                          {Number.isFinite(c.score) && ` · ${c.score.toFixed(2)}`}
                        </button>
                      ))}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
          <div className="h-3.5" />
          <div aria-hidden className="h-px bg-line" />
        </ol>
      </div>
    </div>
  );
}

function Cites({ ids, active, onCite }: { ids?: number[]; active?: number; onCite: (n: number) => void }) {
  if (!ids?.length) return null;
  return (
    <>
      {ids.map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onCite(n)}
          aria-label={`查看片段 ${n} 原文`}
          className={cn(
            'mx-0.5 inline-flex items-center rounded-[4px] px-1 align-[1px] font-num text-[11px] leading-[17px] font-medium transition-colors',
            active === n ? 'bg-ink text-white' : 'bg-blue/10 text-blue hover:bg-blue/20',
          )}
        >
          片段 {n}
        </button>
      ))}
    </>
  );
}

const Caret = () => <span aria-hidden className="ml-0.5 inline-block h-[15px] w-[7px] animate-caret rounded-[1.5px] bg-ink align-[-2px]" />;

function Body({ blocks, shown, streaming, activeCite, onCite }: { blocks: AnswerBlock[]; shown: number; streaming: boolean; activeCite?: number; onCite: (n: number) => void }) {
  const parts = revealBlocks(blocks, shown);
  return (
    <div className="flex flex-col gap-3">
      {parts.map(({ block, title, text, complete }, i) => {
        const tail = streaming && i === parts.length - 1;
        if (block.kind === 'item')
          return (
            <div key={i} className="flex gap-3">
              <span className="flex size-[22px] shrink-0 items-center justify-center rounded-full bg-soft font-num text-[11px] font-semibold text-ink">{block.n}</span>
              <div className="flex min-w-0 flex-col gap-1">
                <p className="text-[14px] font-medium text-ink">
                  {title}
                  {tail && !text && <Caret />}
                </p>
                {text && (
                  <p className="text-[13px] leading-[21px] text-text2">
                    {text}
                    {complete && <Cites ids={block.cite} active={activeCite} onCite={onCite} />}
                    {tail && !complete && <Caret />}
                  </p>
                )}
              </div>
            </div>
          );
        return (
          <p key={i} className="text-[14px] leading-[25px] text-ink">
            {text}
            {complete && <Cites ids={block.cite} active={activeCite} onCite={onCite} />}
            {tail && <Caret />}
          </p>
        );
      })}
      {streaming && !parts.length && (
        <p>
          <Caret />
        </p>
      )}
    </div>
  );
}

function plainText(blocks: AnswerBlock[]) {
  return blocks.map((b) => (b.kind === 'item' ? `${b.n}. ${b.title}：${b.text}` : b.text)).join('\n');
}

interface Props {
  m: AssistantMessage;
  last: boolean;
  activeCite?: number;
  onCite: (n: number) => void;
  onRegenerate: (model?: string) => void;
  onFeedback: (v?: 'up') => void;
  /** F7「换个模型重试」：可用的其他模型 */
  altModel?: string;
}

/** 助手回答：头部（logo + 模型 · 检索 · 用时）→ 思考过程 → 正文 / 错误卡片 → 操作 */
export function AssistantAnswer({ m, last, activeCite, onCite, onRegenerate, onFeedback, altModel }: Props) {
  const toast = useToast();
  const navigate = useNavigate();
  const streaming = m.status === 'streaming';
  const meta =
    m.status === 'error'
      ? `检索 ${m.chunks.length} 个片段 · 生成中断`
      : m.status === 'done'
        ? `检索 ${m.chunks.length} 个片段${m.totalElapsed !== undefined ? ` · ${m.totalElapsed.toFixed(1)}s` : ''}`
        : m.status === 'stopped'
          ? '已停止生成'
          : '正在生成…';

  return (
    <article aria-label="LinkRag 的回答" aria-busy={m.status === 'thinking' || streaming} className="flex gap-3.5">
      {/* 头像列：思考中为羽毛笔书写动效，其余为静态羽毛 */}
      <div className="flex w-14 shrink-0 justify-center pt-0.5">{m.status === 'thinking' ? <FeatherMark writing className="-mt-2.5" /> : <FeatherMark size={28} />}</div>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[22px] items-center gap-2">
          <span className="font-num text-[12px] font-semibold text-ink">LinkRag</span>
          <span className="text-[11px] text-muted">
            <span className="font-num">{m.model}</span> · {meta}
          </span>
        </header>
        <div className="h-3" />
        <Thinking m={m} onCite={onCite} />
        {(m.blocks.length > 0 || streaming) && (
          <div className="pt-4">
            <Body blocks={m.blocks} shown={m.shown} streaming={streaming} activeCite={activeCite} onCite={onCite} />
          </div>
        )}
        {m.status === 'stopped' && <p className="pt-3 text-[11.5px] text-muted">已停止生成{m.shown ? '，以上为已输出的内容' : ''}。</p>}
        {m.status === 'error' && m.error && (
          <div role="alert" className="mt-4 flex flex-col gap-2.5 rounded-[10px] border border-[#f2cfcb] bg-[#fdf2f1] px-[17px] py-4">
            <p className="flex items-center gap-2 text-[13.5px] font-medium text-ink">
              <AlertTriangle aria-hidden className="size-4 text-red" />
              回答生成失败
            </p>
            <p className="text-[12.5px] leading-5 text-text2">{m.error.message}</p>
            <div className="flex gap-2 pt-1">
              <Button icon={<RefreshCw aria-hidden className="size-3" />} onClick={() => onRegenerate()}>
                重新生成
              </Button>
              {altModel && (
                <Button variant="secondary" onClick={() => onRegenerate(altModel)}>
                  换个模型重试
                </Button>
              )}
              <Button variant="secondary" onClick={() => navigate('/models')}>
                前往模型配置
              </Button>
            </div>
            <p className="font-num text-[10.5px] text-muted">
              请求 ID {m.error.requestId} · {m.error.at}
            </p>
          </div>
        )}
        {(m.status === 'done' || m.status === 'stopped') && (
          <div className="flex items-center gap-1 pt-3 text-muted">
            <IconAction
              label="复制回答"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(plainText(m.blocks));
                  toast('已复制回答', { tone: 'success' });
                } catch {
                  toast('复制失败，请手动选择文本', { tone: 'error' });
                }
              }}
            >
              <Copy />
            </IconAction>
            {last && (
              <IconAction label="重新生成" onClick={() => onRegenerate()}>
                <RefreshCw />
              </IconAction>
            )}
            <IconAction label={m.feedback ? '取消有帮助' : '有帮助'} pressed={!!m.feedback} onClick={() => onFeedback(m.feedback ? undefined : 'up')}>
              <ThumbsUp className={cn(m.feedback && 'fill-current text-ink')} />
            </IconAction>
          </div>
        )}
      </div>
    </article>
  );
}

function IconAction({ label, onClick, pressed, children }: { label: string; onClick: () => void; pressed?: boolean; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} aria-pressed={pressed} onClick={onClick} className="rounded-md p-1.5 hover:bg-soft hover:text-ink [&>svg]:size-3.5">
      {children}
    </button>
  );
}
