import { AlertTriangle, Check, Power, X } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { cn } from '@/lib/cn';
import { fileCount, fileStats, updateDataset } from '@/services/datasets';
import type { Dataset } from '@/types';

interface Props {
  dataset: Dataset | null;
  onClose: () => void;
  onDisabled: (ds: Dataset) => void;
}

function Impact({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-[9px] text-[12px] text-text2">
      <span className={cn('flex size-4 shrink-0 items-center justify-center rounded-full', ok ? 'bg-green/14 text-green' : 'bg-muted/14 text-muted')}>
        {ok ? <Check className="size-2.5" strokeWidth={3} /> : <X className="size-2.5" strokeWidth={3} />}
      </span>
      {children}
    </li>
  );
}

/** C12 停用知识库确认 */
export function DisableDatasetDialog({ dataset, onClose, onDisabled }: Props) {
  const [busy, setBusy] = useState(false);
  if (!dataset) return null;
  const running = fileStats(dataset.id).parsing;

  const confirm = async () => {
    setBusy(true);
    await updateDataset(dataset.id, { status: 'disabled' });
    setBusy(false);
    onDisabled(dataset);
  };

  return (
    <Dialog
      open
      onClose={onClose}
      width={440}
      icon={
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-amber/12 text-amber">
          <Power className="size-[17px]" />
        </span>
      }
      title={`停用「${dataset.name}」？`}
      description="停用是可恢复的操作，适合暂时不希望被检索的资料。"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button icon={<Power className="size-3" />} onClick={confirm} disabled={busy} data-autofocus>
            停用知识库
          </Button>
        </>
      }
    >
      <ul className="flex flex-col gap-[9px] rounded-xl bg-soft px-3.5 py-3">
        <Impact ok={false}>对话中无法再选择，也不会参与检索</Impact>
        <Impact ok={false}>不能上传或解析新文件</Impact>
        <Impact ok>{fileCount(dataset.id)} 个文件、分块与解析配置全部保留</Impact>
        <Impact ok>{dataset.conversationCount} 个历史对话仍可查看</Impact>
      </ul>
      {running > 0 && (
        <div className="mt-3.5 flex items-center gap-2 rounded-[9px] bg-amber/8 px-3 py-[9px] text-[11.5px] text-text2">
          <AlertTriangle aria-hidden className="size-[13px] shrink-0 text-amber" />
          {running} 个文件正在解析，停用后将暂停，重新启用时继续。
        </div>
      )}
    </Dialog>
  );
}
