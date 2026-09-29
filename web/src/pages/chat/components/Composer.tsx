import { ArrowUp, Database, Square, X } from 'lucide-react';
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react';

import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { QUESTION_MAX } from '@/services/chat';
import { fileCount } from '@/services/datasets';
import { useStore } from '@/services/useStore';

import { DatasetPicker, ModelPicker } from './Pickers';

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder: string;
  datasetIds: string[];
  onDatasets: (ids: string[]) => void;
  model: string;
  onModel: (name: string) => void;
  /** 生成中：发送按钮变为停止 */
  busy?: boolean;
  onStop?: () => void;
  /** 新对话页的大号输入框 */
  hero?: boolean;
  autoFocus?: boolean;
  /** 输入框下方的提示行 */
  note?: ReactNode;
}

/**
 * 输入框（复刻 LinkCV 助手 / V3 稿）：已选知识库以标签显示在输入框上方，可逐个移除；
 * 圆角输入区 + 右下角圆形发送键；底部一行为「添加知识库」与模型选择。
 * Enter 发送、Shift + Enter 换行；高度随内容增长。
 */
export function Composer({ value, onChange, onSubmit, placeholder, datasetIds, onDatasets, model, onModel, busy, onStop, hero, autoFocus, note }: Props) {
  const toast = useToast();
  const ref = useRef<HTMLTextAreaElement>(null);
  const datasets = useStore((s) => s.datasets);
  const selected = datasetIds.map((id) => datasets.find((d) => d.id === id)).filter((d) => !!d);
  const canSend = !busy && !!value.trim() && datasetIds.length > 0;

  useEffect(() => {
    const el = ref.current;
    if (!el || hero) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [value, hero]);

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canSend) onSubmit();
      else if (!datasetIds.length && value.trim()) toast('请先选择知识库', { tone: 'error' });
    }
  };

  return (
    <div className="flex w-full flex-col gap-1.5">
      {selected.length > 0 && (
        <ul aria-label="已选知识库" className="flex flex-wrap gap-1.5 px-1">
          {selected.map((d) => (
            <li key={d.id} className="flex h-6 items-center gap-[5px] rounded-[7px] border border-line bg-white pr-1 pl-1.5 text-[12px]">
              <Database aria-hidden className="size-3 text-text2" />
              <span className="max-w-[180px] truncate font-medium text-ink">{d.name}</span>
              <span className="font-num text-[11px] text-muted">{fileCount(d.id)}</span>
              <button
                type="button"
                aria-label={`移除知识库 ${d.name}`}
                onClick={() => onDatasets(datasetIds.filter((x) => x !== d.id))}
                className="flex size-4 items-center justify-center rounded text-muted hover:bg-soft hover:text-ink"
              >
                <X aria-hidden className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="relative">
        <textarea
          ref={ref}
          rows={1}
          autoFocus={autoFocus}
          value={value}
          maxLength={QUESTION_MAX}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label="输入问题"
          className={cn(
            'block w-full resize-none rounded-[18px] border bg-white text-ink transition-[border-color,box-shadow] outline-none placeholder:text-[#a3a39c] focus:border-[#b9b9b2]',
            hero
              ? 'h-[152px] border-[#cfcfc9] pt-[22px] pr-[76px] pb-12 pl-[22px] text-[16px] leading-[26px] shadow-[0_8px_18px_rgba(31,31,27,0.08)]'
              : 'min-h-[58px] border-[#d6d6d0] py-[17px] pr-[58px] pl-[18px] text-[14px] leading-[22px] shadow-[0_2px_8px_rgba(15,15,12,0.05)]',
          )}
        />
        {value.length > QUESTION_MAX * 0.8 && (
          <span className={cn('absolute font-num text-[10.5px]', hero ? 'right-[78px] bottom-[34px]' : 'right-[58px] bottom-[22px]', value.length >= QUESTION_MAX ? 'text-red' : 'text-muted')}>
            {value.length} / {QUESTION_MAX}
          </span>
        )}
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="停止生成"
            aria-keyshortcuts="Escape"
            className={cn('absolute flex items-center justify-center rounded-full bg-ink text-white hover:bg-[#33332f]', hero ? 'right-5 bottom-5 size-[46px]' : 'right-[13px] bottom-[13px] size-8')}
          >
            <Square aria-hidden className="size-3 fill-current" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSend}
            aria-label="发送"
            className={cn(
              'absolute flex items-center justify-center rounded-full text-white transition-colors',
              hero ? 'right-5 bottom-5 size-[46px]' : 'right-[13px] bottom-[13px] size-8',
              canSend ? 'bg-ink shadow-[0_4px_10px_rgba(0,0,0,0.12)] hover:bg-[#33332f]' : 'bg-[#c9c9c3]',
            )}
          >
            <ArrowUp aria-hidden className={hero ? 'size-[18px]' : 'size-4'} strokeWidth={2.2} />
          </button>
        )}
      </div>
      <div className="flex min-h-7 items-center gap-2 px-1">
        <DatasetPicker plain value={datasetIds} onChange={onDatasets} warn={!datasetIds.length} />
        {note}
        <span className="flex-1" />
        <ModelPicker plain value={model} onChange={onModel} />
      </div>
    </div>
  );
}
