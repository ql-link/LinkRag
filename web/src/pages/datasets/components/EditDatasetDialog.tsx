import { Copy, SlidersHorizontal, X } from 'lucide-react';
import { useEffect, useId, useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { TextArea, TextInput } from '@/components/ui/Field';
import { ModelSelect } from '@/components/ui/Select';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/contexts/ToastContext';
import { formatCount } from '@/lib/format';
import { DESC_MAX, fileCount, NAME_MAX, updateDataset } from '@/services/datasets';
import type { Dataset } from '@/types';

interface Props {
  dataset: Dataset | null;
  onClose: () => void;
  /** 在编辑弹窗中切换为停用时，交给外层走停用确认流程 */
  onRequestDisable: (ds: Dataset) => void;
}

function Counter({ value, max }: { value: number; max: number }) {
  return <span className="ml-auto font-num text-[10.5px] font-medium text-faint">{`${value} / ${max}`}</span>;
}

/** C11 编辑知识库：左侧表单 + 右侧状态与概况 */
export function EditDatasetDialog({ dataset, onClose, onRequestDisable }: Props) {
  const toast = useToast();
  const titleId = useId();
  const nameId = useId();
  const descId = useId();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!dataset) return;
    setName(dataset.name);
    setDescription(dataset.description);
    setError('');
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [dataset, onClose]);

  if (!dataset) return null;
  const enabled = dataset.status === 'enabled';

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setError('请填写知识库名称');
    setSaving(true);
    try {
      await updateDataset(dataset.id, { name: name.trim(), description: description.trim() });
      toast('已保存知识库信息', { tone: 'success' });
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const toggleStatus = async (next: boolean) => {
    if (!next) return onRequestDisable(dataset);
    await updateDataset(dataset.id, { status: 'enabled' });
    toast(`已重新启用「${dataset.name}」`, { tone: 'success' });
  };

  const copyId = () => {
    void navigator.clipboard?.writeText(dataset.id);
    toast('已复制知识库 ID', { tone: 'success' });
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(29,29,27,0.28)] p-6" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="flex w-[700px] overflow-hidden rounded-[18px] bg-white shadow-dialog">
        <form onSubmit={save} noValidate className="flex w-[440px] shrink-0 flex-col px-7 pt-[26px] pb-[22px]">
          <h2 id={titleId} className="font-serif text-[20px] font-semibold text-ink">
            编辑知识库
          </h2>
          <p className="mt-1.5 text-[12.5px] text-text2">修改名称和描述，保存后立即生效。</p>
          <div className="mt-[22px] flex flex-col gap-4">
            <div className="flex flex-col gap-[7px]">
              <label htmlFor={nameId} className="flex items-center gap-1 text-[12px] font-medium text-ink">
                名称<span className="font-normal text-red">*</span>
                <Counter value={name.length} max={NAME_MAX} />
              </label>
              <TextInput
                id={nameId}
                autoFocus
                value={name}
                maxLength={NAME_MAX}
                invalid={!!error}
                onChange={(e) => {
                  setName(e.target.value);
                  setError('');
                }}
              />
              {error && <p role="alert" className="text-[11.5px] text-red">{error}</p>}
            </div>
            <div className="flex flex-col gap-[7px]">
              <label htmlFor={descId} className="flex items-center gap-1 text-[12px] font-medium text-ink">
                描述
                <Counter value={description.length} max={DESC_MAX} />
              </label>
              <TextArea id={descId} value={description} maxLength={DESC_MAX} onChange={(e) => setDescription(e.target.value)} />
              <p className="text-[11px] text-muted">对话中选择知识库时会展示这段描述</p>
            </div>
            <div className="flex flex-col gap-[7px]">
              <div className="flex items-center gap-1.5 text-[12px] font-medium text-ink">
                向量模型
                <span className="rounded-[5px] bg-muted/10 px-[7px] py-[3px] text-[10.5px] leading-none text-muted">创建后不可修改</span>
              </div>
              <div className="flex gap-2.5">
                <ModelSelect locked value={dataset.denseModel} options={[]} className="flex-1" ariaLabel="稠密向量模型" />
                <ModelSelect locked value={dataset.sparseModel} options={[]} className="flex-1" ariaLabel="稀疏向量模型" />
              </div>
              <p className="text-[11px] text-muted">如需更换向量模型，请新建知识库并重新上传文件。</p>
            </div>
          </div>
          <div className="mt-6 flex items-center gap-2.5">
            <Link to={`/datasets/${dataset.id}/config`} onClick={onClose} className="flex items-center gap-1.5 text-[12px] text-text2 hover:text-ink">
              <SlidersHorizontal aria-hidden className="size-3" />
              解析配置
            </Link>
            <span className="flex-1" />
            <Button variant="secondary" onClick={onClose}>
              取消
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? '保存中…' : '保存'}
            </Button>
          </div>
        </form>
        <aside className="flex w-[260px] flex-col border-l border-divider bg-[#fafaf8] p-[22px]">
          <button type="button" onClick={onClose} aria-label="关闭" className="self-end rounded-md p-0.5 text-muted hover:bg-soft hover:text-ink">
            <X className="size-4" />
          </button>
          <p className="mt-1.5 text-[11px] text-muted">状态</p>
          <div className="mt-2 flex items-center rounded-[10px] border border-line bg-white px-3 py-2.5">
            <div className="flex flex-col gap-[3px]">
              <span className="text-[12.5px] font-medium text-ink">{enabled ? '已启用' : '已停用'}</span>
              <span className="text-[10.5px] text-muted">{enabled ? '可在对话中被检索' : '对话中不可选择'}</span>
            </div>
            <span className="flex-1" />
            <Switch checked={enabled} onChange={toggleStatus} tone="green" label="启用知识库" />
          </div>
          <p className="mt-5 text-[11px] text-muted">概况</p>
          <div className="mt-2 flex gap-2">
            {[
              [formatCount(fileCount(dataset.id)), '文件'],
              [formatCount(dataset.chunkCount), '分块'],
              [formatCount(dataset.conversationCount), '对话'],
            ].map(([v, l]) => (
              <div key={l} className="flex flex-1 flex-col gap-[3px] rounded-[9px] border border-line bg-white px-2.5 py-2">
                <span className="font-num text-[15px] font-semibold text-ink">{v}</span>
                <span className="text-[10.5px] text-muted">{l}</span>
              </div>
            ))}
          </div>
          <p className="mt-5 text-[11px] text-muted">信息</p>
          <dl className="mt-1.5 text-[11.5px]">
            <div className="flex items-center justify-between py-1.5">
              <dt className="text-muted">知识库 ID</dt>
              <dd className="flex items-center gap-1.5 font-num font-medium text-text2">
                {dataset.id}
                <button type="button" onClick={copyId} aria-label="复制知识库 ID" className="text-muted hover:text-ink">
                  <Copy className="size-[11px]" />
                </button>
              </dd>
            </div>
            {[
              ['存储占用', dataset.storage],
              ['创建者', dataset.createdBy],
              ['创建时间', dataset.createdAt],
              ['最近更新', dataset.updatedAt],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between py-1.5">
                <dt className="text-muted">{k}</dt>
                <dd className="text-text2">{v}</dd>
              </div>
            ))}
          </dl>
        </aside>
      </div>
    </div>,
    document.body,
  );
}
