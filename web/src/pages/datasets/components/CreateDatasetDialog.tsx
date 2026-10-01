import { AlertCircle } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextArea, TextInput } from '@/components/ui/Field';
import { ModelSelect } from '@/components/ui/Select';
import { createDataset, DESC_MAX, embeddingModels, NAME_MAX } from '@/services/datasets';
import { useModels } from '@/services/models';
import type { Dataset } from '@/types';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (ds: Dataset) => void;
}

/** C2 新建知识库弹窗 */
export function CreateDatasetDialog({ open, onClose, onCreated }: Props) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  // 选项来自已接入的向量模型（真实模式）；默认模型排首位
  const denseOptions = useModels(() => embeddingModels('dense'));
  const sparseOptions = useModels(() => embeddingModels('sparse'));
  const [denseChoice, setDense] = useState<string>();
  const [sparseChoice, setSparse] = useState<string>();
  const dense = denseChoice ?? denseOptions[0] ?? '';
  const sparse = sparseChoice ?? sparseOptions[0] ?? '';
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const close = () => {
    setName('');
    setDescription('');
    setError('');
    onClose();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setError('请填写知识库名称');
    setSubmitting(true);
    try {
      const ds = await createDataset({ name, description, denseModel: dense, sparseModel: sparse });
      close();
      onCreated(ds);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title="新建知识库" description="填写基础信息并选择向量模型。">
      <form onSubmit={submit} noValidate>
        <div className="flex flex-col gap-4">
          <Field label="名称" required error={error}>
            {(id, d) => (
              <TextInput
                id={id}
                value={name}
                maxLength={NAME_MAX}
                invalid={!!error}
                aria-describedby={d}
                placeholder="例如：产品知识库"
                onKeyDown={(e) => {
                  // 名称框的回车只用于输入（包括 IME 选词），创建需显式激活按钮。
                  if (e.key === 'Enter') e.preventDefault();
                }}
                onChange={(e) => {
                  setName(e.target.value);
                  setError('');
                }}
              />
            )}
          </Field>
          <Field label="描述" hint={`选填，最多 ${DESC_MAX} 字`}>
            {(id, d) => (
              <TextArea id={id} aria-describedby={d} value={description} maxLength={DESC_MAX} onChange={(e) => setDescription(e.target.value)} placeholder="用于知识问答、产品文档…" />
            )}
          </Field>
          <div className="flex gap-3">
            <div className="flex-1">
              <Field label="稠密向量模型" required>
                {(id) => <ModelSelect id={id} value={dense} options={denseOptions} onChange={setDense} />}
              </Field>
            </div>
            <div className="flex-1">
              <Field label="稀疏向量模型" required>
                {(id) => <ModelSelect id={id} value={sparse} options={sparseOptions} onChange={setSparse} />}
              </Field>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-[9px] bg-amber/8 px-3 py-2.5 text-[11.5px] text-text2">
            <AlertCircle aria-hidden className="size-[13px] shrink-0 text-amber" />
            向量模型创建后不可修改，已按「模型配置」中的默认模型预选。
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2.5">
          <Button variant="secondary" onClick={close}>
            取消
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? '创建中…' : '创建'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
