/** 日志详情抽屉（设计稿 E2 Drawer 460px）：全部字段、exception/raw 等宽展示、复制与按 trace 查询、上一条/下一条 */
import { Copy, Filter, X } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';

import { Chip } from '@/components/ui/Chip';
import { useToast } from '@/contexts/ToastContext';

import { actionBtn } from '../StateFeedback';
import { fmtFull, type LogEntry } from './api';
import { LevelBadge } from './LevelBadge';

interface Props {
  entry: LogEntry;
  /** 全局行号（第几条），用于展示 row */
  rowNo: number;
  onClose: () => void;
  onTrace: (traceId: string) => void;
  onPrev?: () => void;
  onNext?: () => void;
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const ta = document.createElement('textarea');
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  ta.remove();
}

const btn = `${actionBtn} flex items-center gap-1.5 px-2.5 py-1 text-[11.5px] font-normal disabled:opacity-40`;

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex min-h-7 items-start gap-3 py-1">
      <dt className="w-20 shrink-0 pt-px text-[11px] text-muted">{k}</dt>
      <dd className="min-w-0 flex-1 text-[12px] break-all text-ink">{children}</dd>
    </div>
  );
}

function Block({ title, children, extra }: { title: string; children: ReactNode; extra?: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center">
        <h3 className="text-[11px] text-muted">{title}</h3>
        {extra && <span className="ml-auto">{extra}</span>}
      </div>
      {children}
    </section>
  );
}

const pre = 'max-h-[260px] overflow-auto rounded-[8px] bg-soft px-3 py-2.5 font-mono text-[11px] leading-[17px] whitespace-pre-wrap break-all text-text2';

export function DetailPanel({ entry: e, rowNo, onClose, onTrace, onPrev, onNext }: Props) {
  const toast = useToast();
  const ref = useRef<HTMLElement>(null);
  const copy = (label: string, text: string) =>
    copyText(text).then(
      () => toast(`已复制 ${label}`, { tone: 'success' }),
      () => toast('复制失败，请手动选择文本', { tone: 'error' }),
    );

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  useEffect(() => ref.current?.focus(), [e]);

  const copyIcon = (label: string, text: string) => (
    <button type="button" aria-label={`复制 ${label}`} title={`复制 ${label}`} onClick={() => copy(label, text)} className="ml-1.5 inline-flex align-middle text-muted hover:text-ink">
      <Copy aria-hidden className="size-3.5" />
    </button>
  );

  return (
    <aside ref={ref} tabIndex={-1} aria-label="日志详情" className="fixed inset-y-0 right-0 z-30 flex w-[460px] max-w-full animate-rise-in flex-col border-l border-line bg-white shadow-dialog outline-none">
      <header className="flex h-[60px] shrink-0 items-center gap-2 border-b border-divider px-5">
        <LevelBadge level={e.level} />
        {e.exception && (
          <Chip tone="red" dot={false}>
            异常
          </Chip>
        )}
        <h2 className="text-[14px] font-medium text-ink">日志详情</h2>
        <button type="button" aria-label="关闭详情" onClick={onClose} className="ml-auto rounded-[6px] p-1 text-muted hover:bg-soft hover:text-ink">
          <X aria-hidden className="size-4" />
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-5">
        <dl className="flex flex-col">
          <Row k="时间">
            <span className="font-num tabular-nums">{fmtFull(e.time)}</span>
          </Row>
          <Row k="service">{e.service ?? '—'}</Row>
          <Row k="trace_id">
            {e.trace_id ? (
              <>
                <span className="font-mono text-[11.5px]">{e.trace_id}</span>
                {copyIcon('trace_id', e.trace_id)}
              </>
            ) : (
              '—'
            )}
          </Row>
          <Row k="logger">
            <span className="font-mono text-[11.5px]">{e.logger_name ?? '—'}</span>
          </Row>
          <Row k="host / pid">
            {e.host ?? '—'} / {e.pid ?? '—'}
          </Row>
          <Row k="row">
            <span className="font-num">#{rowNo}</span>
          </Row>
        </dl>

        <Block title="message" extra={e.message ? copyIcon('message', e.message) : undefined}>
          <p className="text-[12.5px] leading-5 break-words whitespace-pre-wrap text-ink">{e.message ?? '—'}</p>
        </Block>

        {e.exception && (
          <Block title="exception" extra={copyIcon('exception', e.exception)}>
            <pre className={`${pre} text-red`}>{e.exception}</pre>
          </Block>
        )}

        {e.raw && (
          <Block title="raw" extra={copyIcon('raw', e.raw)}>
            <pre className={pre}>{e.raw}</pre>
          </Block>
        )}
      </div>

      <footer className="flex h-[50px] shrink-0 items-center gap-2 border-t border-divider px-5">
        <button type="button" disabled={!e.trace_id} onClick={() => e.trace_id && copy('trace_id', e.trace_id)} className={btn}>
          <Copy aria-hidden className="size-3.5" />
          复制 trace_id
        </button>
        <button type="button" disabled={!e.trace_id} onClick={() => e.trace_id && onTrace(e.trace_id)} className={btn}>
          <Filter aria-hidden className="size-3.5" />
          按此 trace 查询
        </button>
        <span className="ml-auto flex gap-2">
          <button type="button" disabled={!onPrev} onClick={onPrev} className={btn}>
            上一条
          </button>
          <button type="button" disabled={!onNext} onClick={onNext} className={btn}>
            下一条
          </button>
        </span>
      </footer>
    </aside>
  );
}
