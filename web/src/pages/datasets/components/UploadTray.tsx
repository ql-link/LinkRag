import { Upload, X } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Progress } from '@/components/ui/Progress';
import type { KbFile } from '@/types';

/** C5 上传中托盘：汇总本批次上传进度 */
export function UploadTray({ batch, onCancel }: { batch: KbFile[]; onCancel: () => void }) {
  const finished = batch.filter((f) => f.status !== 'uploading').length;
  const avg = batch.reduce((n, f) => n + (f.status === 'uploading' ? f.progress : 100), 0) / batch.length;
  const remain = Math.max(1, Math.round(((100 - avg) / 100) * batch.length * 3));

  return (
    <section aria-label="上传进度" className="mb-[22px] flex flex-col gap-2.5 rounded-[14px] border border-line bg-white px-[18px] py-3.5 shadow-card">
      <div className="flex items-center gap-2.5">
        <Upload aria-hidden className="size-3.5 text-text2" />
        <span className="text-[13px] font-medium text-ink">
          正在上传 {batch.length} 个文件 · {finished} / {batch.length}
        </span>
        <span className="text-[11.5px] text-muted">剩余约 {remain} 秒</span>
        <span className="flex-1" />
        <Button variant="secondary" icon={<X className="size-3" />} onClick={onCancel}>
          取消全部
        </Button>
      </div>
      <Progress value={avg} label="本批上传总进度" />
    </section>
  );
}
