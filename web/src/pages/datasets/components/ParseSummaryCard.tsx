import { Check, RefreshCw, Upload } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Progress } from '@/components/ui/Progress';
import type { Dataset } from '@/types';

interface Props {
  dataset: Dataset;
  stats: { total: number; done: number; parsing: number; failed: number };
  onUpload: () => void;
  onParseAll: () => void;
  onClearFailed: () => void;
  disabled?: boolean;
}

/** C4 顶部解析进度卡片 */
export function ParseSummaryCard({ dataset, stats, onUpload, onParseAll, onClearFailed, disabled }: Props) {
  const pct = stats.total ? (stats.done / stats.total) * 100 : 0;
  const detail = [
    stats.parsing > 0 && `${stats.parsing} 个文件解析中`,
    stats.failed > 0 && `${stats.failed} 个失败`,
    `稠密向量 ${dataset.denseModel}`,
    `稀疏向量 ${dataset.sparseModel}`,
  ].filter(Boolean);

  return (
    <section className="flex h-[190px] gap-7 rounded-2xl border border-line bg-white py-[7px] pr-6 pl-[7px] shadow-card">
      <div aria-hidden className="relative h-[176px] w-[244px] shrink-0 rounded-[11px] bg-soft">
        <div className="absolute top-[26px] left-[70px] h-[122px] w-[104px] overflow-hidden rounded-xl border border-line bg-white shadow-[0_6px_16px_0_rgba(0,0,0,0.08)]">
          <div className="flex h-[26px] items-center justify-center bg-ink text-[10px] font-medium text-white">拖入文件</div>
          <Upload className="mx-auto mt-[11px] size-[30px] text-text2" strokeWidth={1.5} />
          <p className="mt-6 text-center text-[11.5px] font-medium text-text2">PDF · MD · ZIP</p>
        </div>
        <span className="absolute top-[112px] left-[158px] flex size-9 items-center justify-center rounded-full bg-green shadow-[0_4px_10px_0_rgba(0,0,0,0.12)]">
          <Check className="size-4 text-white" strokeWidth={2.5} />
        </span>
      </div>
      <div className="flex min-w-0 flex-1 flex-col pt-[22px] pb-2.5">
        <p className="text-[11px] text-muted">
          {disabled ? '知识库已停用 · 解析已暂停' : `解析队列 · 上传后立即解析 ${dataset.autoParse ? '已开启' : '已关闭'}`}
        </p>
        <p className="mt-2 font-serif text-[19px] font-semibold text-ink">
          {stats.done} / {stats.total} 已完成解析
        </p>
        <p className="mt-2.5 truncate text-[13px] text-text2">{detail.join(' · ')}</p>
        <div className="flex-1" />
        <div className="flex items-center gap-3">
          <Progress value={pct} className="w-40" label="解析完成度" />
          <p className="text-[11px] text-muted">
            {pct.toFixed(1)}%
            {stats.failed > 0 && (
              <>
                {' · '}
                <button type="button" onClick={onClearFailed} className="hover:text-ink hover:underline">
                  清除 {stats.failed} 个失败文件
                </button>
              </>
            )}
          </p>
          <span className="flex-1" />
          <Button variant="secondary" icon={<RefreshCw className="size-3" />} onClick={onParseAll} disabled={disabled}>
            全部解析
          </Button>
          <Button icon={<Upload className="size-3" />} onClick={onUpload} disabled={disabled}>
            上传文件
          </Button>
        </div>
      </div>
    </section>
  );
}
