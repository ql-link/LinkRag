/** D9 紧急停用平台配置：需输入模型名确认 */
import { AlertTriangle } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextInput } from '@/components/ui/Field';
import { useToast } from '@/contexts/ToastContext';

import { emergencyDisableConfig, type LlmConfig } from './api';
import { errMsg } from './helpers';

export function EmergencyDisableDialog({ config, inUse, onClose, onDone }: { config: LlmConfig | null; inUse?: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => setText(''), [config]);
  const ok = !!config && text.trim() === config.modelName;

  async function submit() {
    if (!config || !ok) return;
    setBusy(true);
    try {
      await emergencyDisableConfig(config.configId);
      toast(`已紧急停用 ${config.displayName || config.modelName}`, { tone: 'success' });
      onDone();
      onClose();
    } catch (e) {
      toast(errMsg(e, '停用失败'), { tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={!!config}
      onClose={onClose}
      width={460}
      icon={
        <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-red/10 text-red">
          <AlertTriangle className="size-4" />
        </span>
      }
      title="紧急停用平台配置"
      description={config && `${config.displayName || config.modelName} · ${config.modelName}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button variant="danger" onClick={submit} disabled={!ok || busy}>
            {busy ? '停用中…' : '确认停用'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="rounded-[10px] border border-red/20 bg-red/5 px-3.5 py-3 text-[12px] leading-5 text-text2">
          {inUse && <span className="mb-1 block font-medium text-red">该配置正在被知识库使用，普通停用已被拒绝。</span>}
          停用后立即生效：所有使用该平台模型的对话与知识库将无法调用，直到重新启用。
        </p>
        <Field label={`输入 ${config?.modelName ?? ''} 以确认`} required>
          {(id) => (
            <TextInput
              id={id}
              value={text}
              placeholder={config?.modelName}
              autoComplete="off"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}
