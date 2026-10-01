import { Eye, MoreHorizontal, RefreshCw, Trash2, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { FileBadge } from '@/components/FileBadge';
import { Chip, type Tone } from '@/components/ui/Chip';
import { Menu } from '@/components/ui/Menu';
import { Progress } from '@/components/ui/Progress';
import { cn } from '@/lib/cn';
import { removeFile, reparseFile } from '@/services/datasets';
import type { KbFile } from '@/types';

const statusView: Record<KbFile['status'], { tone: Tone; label: (f: KbFile) => string; bar?: string }> = {
  uploading: { tone: 'blue', label: (f) => `上传中 ${f.progressEstimated ? '≈' : ''}${f.progress}%`, bar: '#3f6fd8' },
  parsing: { tone: 'amber', label: (f) => `解析中 ${f.progressEstimated ? '≈' : ''}${f.progress}%`, bar: '#d9912b' },
  queued: { tone: 'gray', label: () => '待解析' },
  done: { tone: 'green', label: () => '已完成' },
  failed: { tone: 'red', label: () => '失败' },
};

/** 文件表格行：类型徽标 / 名称（进度与说明）/ 类型·大小 / 状态 / 更新 / 操作 */
export function FileRow({ file, disabled }: { file: KbFile; disabled?: boolean }) {
  const navigate = useNavigate();
  const view = statusView[file.status];
  const openDetail = () => navigate(`/datasets/${file.datasetId}/files/${file.id}`);
  const note = file.note ?? (file.status === 'done' && file.chunkCount ? `${file.chunkCount} 个分块` : undefined);

  return (
    <li className="flex items-center gap-3 border-b border-divider py-[9px]">
      <FileBadge type={file.type} />
      <div className="flex min-w-0 flex-1 flex-col gap-[5px]">
        <button
          type="button"
          onClick={openDetail}
          disabled={file.status === 'uploading'}
          className="truncate text-left text-[13px] font-medium text-ink hover:underline disabled:no-underline"
        >
          {file.name}
        </button>
        {view.bar && <Progress value={file.progress} color={view.bar} className="w-[240px] max-w-full" label={`${file.name} 进度`} />}
        {note && (
          <p className={cn('truncate text-[11px]', file.status === 'failed' ? 'text-red' : 'text-muted')}>
            {note}
            {file.status === 'failed' && !disabled && (
              <>
                {' · '}
                <button type="button" onClick={() => reparseFile(file.id)} className="font-medium hover:underline">
                  重新解析
                </button>
              </>
            )}
          </p>
        )}
      </div>
      <span className="w-[110px] shrink-0 font-num text-[11.5px] font-medium text-muted">
        {file.type} · {file.size}
      </span>
      <span className="w-[110px] shrink-0">
        <Chip tone={view.tone}>{view.label(file)}</Chip>
      </span>
      <span className={cn('w-14 shrink-0 text-right text-[11.5px]', /^\d/.test(file.updatedAt) ? 'text-muted' : 'text-ink')}>{file.updatedAt}</span>
      {file.status === 'uploading' ? (
        <button type="button" aria-label={`取消上传 ${file.name}`} onClick={() => removeFile(file.id)} className="rounded p-0.5 text-muted hover:bg-soft hover:text-ink">
          <X className="size-3.5" />
        </button>
      ) : (
        <Menu
          width={150}
          items={[
            { key: 'view', label: '查看详情', icon: <Eye />, onSelect: openDetail },
            ...(!disabled && file.status !== 'parsing' ? [{ key: 'parse', label: '重新解析', icon: <RefreshCw />, onSelect: () => reparseFile(file.id) }] : []),
            { key: 'del', label: '删除文件', icon: <Trash2 />, danger: true, divider: true, onSelect: () => removeFile(file.id) },
          ]}
          trigger={({ toggle, open }) => (
            <button
              type="button"
              aria-label={`${file.name} 更多操作`}
              onClick={toggle}
              className={cn('rounded p-0.5 text-muted hover:bg-soft hover:text-ink', open && 'bg-soft text-ink')}
            >
              <MoreHorizontal className="size-3.5" />
            </button>
          )}
        />
      )}
    </li>
  );
}
