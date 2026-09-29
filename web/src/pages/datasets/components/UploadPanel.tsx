import { Check, FileArchive, Folder, MessageSquare, Plus, SlidersHorizontal, Upload } from 'lucide-react';
import { useRef, useState, type DragEvent } from 'react';
import { Link } from 'react-router-dom';

import { DocTrio } from '@/components/DocIllustration';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';

export const ACCEPT = '.pdf,.doc,.docx,.md,.markdown,.txt,.xls,.xlsx,.csv,.zip';
export const MAX_SIZE = 50 * 1024 * 1024;

interface PickerProps {
  onFiles: (files: File[]) => void;
}

/** 隐藏的文件选择器：普通文件 / 文件夹 / ZIP */
export function useFilePickers({ onFiles }: PickerProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);
  const zipRef = useRef<HTMLInputElement>(null);
  const handle = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (files.length) onFiles(files);
  };
  const inputs = (
    <>
      <input ref={fileRef} type="file" multiple accept={ACCEPT} hidden onChange={handle} data-testid="file-input" />
      <input ref={dirRef} type="file" multiple hidden onChange={handle} {...{ webkitdirectory: '' }} />
      <input ref={zipRef} type="file" accept=".zip" hidden onChange={handle} />
    </>
  );
  return {
    inputs,
    pickFiles: () => fileRef.current?.click(),
    pickFolder: () => dirRef.current?.click(),
    pickZip: () => zipRef.current?.click(),
  };
}

interface DropzoneProps extends PickerProps {
  autoParse: boolean;
  onAutoParseChange: (v: boolean) => void;
  disabled?: boolean;
}

/** C3 空知识库的大号拖拽上传区 */
export function Dropzone({ onFiles, autoParse, onAutoParseChange, disabled }: DropzoneProps) {
  const [over, setOver] = useState(false);
  const pickers = useFilePickers({ onFiles });
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(files);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        'flex flex-col items-center gap-3 rounded-2xl border border-dashed bg-soft pt-11 pb-10 transition-colors',
        over ? 'border-ink bg-active/60' : 'border-dash',
        disabled && 'opacity-60',
      )}
    >
      {pickers.inputs}
      <DocTrio />
      <p className="text-[15px] font-medium text-ink">拖拽文件到这里，或点击上传</p>
      <p className="text-[12px] text-muted">支持 PDF、Word、Markdown、TXT、Excel；单个文件不超过 50 MB</p>
      <div className="mt-1 flex gap-2.5">
        <Button icon={<Upload className="size-3" />} onClick={pickers.pickFiles} disabled={disabled}>
          选择文件
        </Button>
        <Button variant="secondary" icon={<Folder className="size-3" />} onClick={pickers.pickFolder} disabled={disabled}>
          上传文件夹
        </Button>
        <Button variant="secondary" icon={<FileArchive className="size-3" />} onClick={pickers.pickZip} disabled={disabled}>
          上传 ZIP
        </Button>
      </div>
      <label className="mt-0.5 flex cursor-pointer items-center gap-[7px] text-[12px] text-text2">
        <input type="checkbox" className="peer sr-only" checked={autoParse} onChange={(e) => onAutoParseChange(e.target.checked)} />
        <span className="flex size-[15px] items-center justify-center rounded border border-line bg-white peer-checked:border-ink peer-checked:bg-ink peer-focus-visible:shadow-ring">
          {autoParse && <Check aria-hidden className="size-2.5 text-white" strokeWidth={3} />}
        </span>
        上传后立即解析
      </label>
    </div>
  );
}

/** C3 “接下来”引导卡片 */
export function NextSteps({ datasetId }: { datasetId: string }) {
  const items = [
    { icon: <SlidersHorizontal />, title: '检查解析配置', desc: '按资料类型开启图片 / 表格增强', to: `/datasets/${datasetId}/config` },
    { icon: <MessageSquare />, title: '上传后开始对话', desc: '回答会附带命中的资料片段' },
    { icon: <Plus />, title: '邀请同事（即将支持）', desc: '团队空间与只读成员' },
  ];
  return (
    <>
      <p className="mt-6 text-[11px] text-muted">接下来</p>
      <div className="mt-[18px] flex gap-4">
        {items.map((it) => {
          const body = (
            <>
              <span className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-soft text-text2 [&>svg]:size-3.5">{it.icon}</span>
              <span className="flex min-w-0 flex-col gap-[3px]">
                <span className="text-[12.5px] font-medium text-ink">{it.title}</span>
                <span className="truncate text-[11px] text-muted">{it.desc}</span>
              </span>
            </>
          );
          const cls = 'flex flex-1 items-center gap-3 rounded-[14px] border border-line bg-white px-4 py-3.5 shadow-card';
          return it.to ? (
            <Link key={it.title} to={it.to} className={cn(cls, 'hover:border-ink/40')}>
              {body}
            </Link>
          ) : (
            <div key={it.title} className={cls}>
              {body}
            </div>
          );
        })}
      </div>
    </>
  );
}
