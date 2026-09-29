import { AlertCircle, Check, Clock, Play, RefreshCw, SlidersHorizontal, X } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { Segmented } from '@/components/ui/Segmented';
import { cn } from '@/lib/cn';
import type { KbFile } from '@/types';

type StepState = 'done' | 'failed' | 'pending';

interface Props {
  file: KbFile;
  pages: number;
  failedPage: number;
  onResume: () => void;
  onRestart: () => void;
  disabled?: boolean;
}

const PARSERS = ['MinerU', 'OpenDataLoader', 'Naive'] as const;

/** C7 右侧：失败原因、解析步骤、处理建议与恢复操作 */
export function FailurePanel({ file, pages, failedPage, onResume, onRestart, disabled }: Props) {
  const [parser, setParser] = useState<(typeof PARSERS)[number]>('MinerU');
  const done = failedPage - 1;
  const steps: { title: string; detail: string; state: StepState }[] = [
    { title: '上传文件', detail: `${file.size} · 09-24 10:02`, state: 'done' },
    { title: '版面分析', detail: `${pages} 页 · 识别到 12 张图片、5 个表格`, state: 'done' },
    { title: '文本抽取', detail: `第 1–${done} 页完成`, state: 'done' },
    { title: 'OCR 识别', detail: `第 ${failedPage} 页超时，已处理 ${done} / ${pages} 页`, state: 'failed' },
    { title: '图片 / 表格增强', detail: '未开始', state: 'pending' },
    { title: '分块与向量化', detail: '未开始', state: 'pending' },
  ];

  return (
    <div className="h-full overflow-y-auto px-8 pt-[30px] pb-10">
      <div className="flex items-center gap-3.5">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-red/10 text-red">
          <AlertCircle className="size-5" />
        </span>
        <div className="flex flex-col gap-[5px]">
          <h2 className="text-[20px] font-semibold text-ink">解析失败</h2>
          <p className="text-[12.5px] text-text2">OCR 识别超时：第 {failedPage} 页处理超过 120 秒</p>
        </div>
      </div>

      <p className="mt-6 text-[11px] text-muted">解析进度</p>
      <ol className="mt-3">
        {steps.map((s, i) => (
          <li key={s.title} className="flex gap-3.5">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  'flex size-5 shrink-0 items-center justify-center rounded-full',
                  s.state === 'done' && 'bg-ink text-white',
                  s.state === 'failed' && 'bg-red text-white',
                  s.state === 'pending' && 'border border-dash bg-white',
                )}
              >
                {s.state === 'done' && <Check className="size-[11px]" strokeWidth={3} />}
                {s.state === 'failed' && <X className="size-[11px]" strokeWidth={3} />}
              </span>
              {i < steps.length - 1 && <span className={cn('h-[26px] w-px', s.state === 'done' ? 'bg-ink' : 'bg-dash')} />}
            </div>
            <div className="flex flex-col gap-[3px] pt-px">
              <span className={cn('text-[13px] font-medium', s.state === 'failed' ? 'text-red' : s.state === 'pending' ? 'text-muted' : 'text-ink')}>{s.title}</span>
              <span className={cn('text-[11.5px]', s.state === 'failed' ? 'text-red' : 'text-muted')}>{s.detail}</span>
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-[18px] flex flex-col gap-2 rounded-xl bg-soft px-4 py-3.5">
        <p className="text-[12.5px] font-medium text-ink">处理建议</p>
        <ul className="flex flex-col gap-2 text-[12px] text-text2">
          {[`从失败处继续解析，已完成的 ${done} 页不会重复处理`, '扫描件较多时，可切换为 OpenDataLoader 方案', '或在解析配置中关闭图片增强以缩短耗时'].map((t) => (
            <li key={t} className="flex gap-2">
              <span className="text-[13px] font-medium text-muted">·</span>
              {t}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-4 flex items-center gap-2.5 rounded-[10px] border border-line py-2.5 pr-2.5 pl-3.5">
        <span className="text-[12px] text-text2">本次解析方案</span>
        <span className="flex-1" />
        <Segmented ariaLabel="本次解析方案" value={parser} onChange={setParser} options={PARSERS.map((p) => ({ value: p, label: p }))} />
      </div>

      <div className="mt-5 flex gap-2.5">
        <Button icon={<Play className="size-3" />} onClick={onResume} disabled={disabled}>
          从第 {failedPage} 页继续解析
        </Button>
        <Button variant="secondary" icon={<RefreshCw className="size-3" />} onClick={onRestart} disabled={disabled}>
          重新完整解析
        </Button>
        <span className="flex-1" />
        <Link
          to={`/datasets/${file.datasetId}/config`}
          className="inline-flex items-center gap-1.5 rounded-[7px] border border-line bg-white py-2 pr-3.5 pl-[13px] text-[12px] text-text2 hover:bg-soft"
        >
          <SlidersHorizontal aria-hidden className="size-3" />
          解析配置
        </Link>
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-[10.5px] text-muted">
        <Clock aria-hidden className="size-[11px]" />
        失败于 09-24 10:05 · 任务 ID parse_{file.id.replace('f_', '4c19e')} · 已自动重试 2 次
      </p>
    </div>
  );
}
