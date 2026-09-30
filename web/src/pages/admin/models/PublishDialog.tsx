/** D7 发布候选为正式能力（同一模型可一次发布多个能力） */
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextInput } from '@/components/ui/Field';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';

import { CAPABILITY_LABEL, publishCandidates, type SyncCandidate } from './api';
import { errMsg, type CandidateGroup } from './helpers';

const publishable = (c: SyncCandidate) => c.reviewStatus !== 'PUBLISHED' && c.matchedProviderModelId === null;

export function PublishDialog({ group, onClose, onDone }: { group: CandidateGroup | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [modelName, setModelName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!group) return;
    const first = group.items[0];
    setModelName(first.modelName);
    setDisplayName(group.items.find((c) => c.displayName)?.displayName ?? '');
    setPicked(new Set(group.items.filter(publishable).map((c) => c.id)));
  }, [group]);

  const toggle = (id: number) =>
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  async function submit() {
    if (!group || picked.size === 0 || !modelName.trim()) return;
    setBusy(true);
    try {
      const res = await publishCandidates([...picked], { modelName: modelName.trim(), displayName: displayName.trim() || undefined });
      toast(`已发布 ${res?.length ?? picked.size} 项模型能力`, { tone: 'success' });
      onDone();
      onClose();
    } catch (e) {
      toast(errMsg(e, '发布失败'), { tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  const src = group?.items[0]?.syncSource === 'MODELS_DEV' ? 'models.dev' : group?.items[0]?.syncSource;
  return (
    <Dialog
      open={!!group}
      onClose={onClose}
      width={500}
      title="发布模型能力"
      description={group && `${group.modelName} · 来源 ${src}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy || picked.size === 0 || !modelName.trim()}>
            {busy ? '发布中…' : `发布 ${picked.size} 项`}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="真实模型名" required error={modelName.trim() ? undefined : '请填写真实模型名'}>
            {(id, d) => <TextInput id={id} aria-describedby={d} value={modelName} onChange={(e) => setModelName(e.target.value)} />}
          </Field>
          <Field label="展示名">
            {(id) => <TextInput id={id} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />}
          </Field>
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-[12px] font-medium text-ink">发布能力</legend>
          {group?.items.map((c) => {
            const ok = publishable(c);
            return (
              <label key={c.id} className={cn('flex items-center gap-3 rounded-[10px] border px-3.5 py-2.5', ok ? 'cursor-pointer border-line' : 'border-divider bg-soft opacity-70')}>
                <input type="checkbox" className="size-3.5 accent-ink" disabled={!ok} checked={picked.has(c.id)} onChange={() => toggle(c.id)} />
                <span className="text-[12.5px] text-ink">
                  {CAPABILITY_LABEL[c.capability] ?? c.capability} {c.capability}
                </span>
                <span className="ml-auto text-[11.5px] text-muted">{ok ? `推断协议 ${c.inferredProtocol ?? '—'}` : '已存在，将跳过'}</span>
              </label>
            );
          })}
          <p className="text-[11.5px] text-muted">已选择 {picked.size} 项</p>
        </fieldset>
        <p className="rounded-[10px] bg-soft px-3.5 py-2.5 text-[11.5px] leading-5 text-text2">发布后默认「已下架」，配置平台 Key 并上架后用户才可选择。</p>
      </div>
    </Dialog>
  );
}
