import { Check, FileText, Layers, MessageSquare, Power, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextInput } from '@/components/ui/Field';
import { formatCount } from '@/lib/format';
import { deleteDataset, fileCount } from '@/services/datasets';
import type { Dataset } from '@/types';

interface Props {
  dataset: Dataset | null;
  onClose: () => void;
  onDeleted: (ds: Dataset) => void;
  onSuggestDisable: (ds: Dataset) => void;
}

/** C14 删除知识库：输入名称确认后才可删除 */
export function DeleteDatasetDialog({ dataset, onClose, onDeleted, onSuggestDisable }: Props) {
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  if (!dataset) return null;
  const matched = typed.trim() === dataset.name;

  const close = () => {
    setTyped('');
    onClose();
  };

  const confirm = async () => {
    if (!matched) return;
    setBusy(true);
    await deleteDataset(dataset.id);
    setBusy(false);
    setTyped('');
    onDeleted(dataset);
  };

  const stats = [
    { icon: <FileText />, value: formatCount(fileCount(dataset.id)), label: '文件' },
    { icon: <Layers />, value: formatCount(dataset.chunkCount), label: '分块与向量' },
    { icon: <MessageSquare />, value: formatCount(dataset.conversationCount), label: '历史对话' },
  ];

  return (
    <Dialog
      open
      onClose={close}
      width={460}
      icon={
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-red/10 text-red">
          <Trash2 className="size-[17px]" />
        </span>
      }
      title={`删除「${dataset.name}」？`}
      description="知识库内的文件与关联配置将无法从前端继续访问，删除后无法恢复。"
      footer={
        <>
          <Button variant="secondary" onClick={close}>
            取消
          </Button>
          <Button variant="danger" icon={<Trash2 className="size-3" />} onClick={confirm} disabled={!matched || busy}>
            永久删除
          </Button>
        </>
      }
    >
      <p className="text-[11px] text-muted">将被删除</p>
      <div className="mt-2 flex gap-2">
        {stats.map((s) => (
          <div key={s.label} className="flex flex-1 items-center gap-2 rounded-[10px] bg-red/5 px-2.5 py-[9px]">
            <span className="text-red [&>svg]:size-[13px]">{s.icon}</span>
            <span className="flex flex-col gap-0.5">
              <span className="font-num text-[13px] font-semibold text-ink">{s.value}</span>
              <span className="text-[10.5px] text-muted">{s.label}</span>
            </span>
          </div>
        ))}
      </div>
      {dataset.status === 'enabled' && (
        <div className="mt-3 flex items-center gap-2 rounded-[9px] bg-soft px-3 py-[9px] text-[11.5px] text-text2">
          <Power aria-hidden className="size-3" />
          <span>
            只是暂时不用？可以先
            <button type="button" onClick={() => onSuggestDisable(dataset)} className="font-medium text-ink hover:underline">
              停用知识库
            </button>
          </span>
        </div>
      )}
      <div className="mt-4">
        <Field label={`输入知识库名称「${dataset.name}」以确认`}>
          {(id) => (
            <TextInput
              id={id}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && confirm()}
              placeholder={dataset.name}
              autoComplete="off"
              trailing={matched ? <Check aria-label="名称匹配" className="size-[13px] text-green" /> : undefined}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}
