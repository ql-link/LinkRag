/** 通用危险操作确认弹窗 */
import { AlertTriangle } from 'lucide-react';
import { useState, type ReactNode } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';

export interface ConfirmState {
  title: string;
  desc: ReactNode;
  okText: string;
  run: () => Promise<void>;
}

export function ConfirmDialog({ state, onClose }: { state: ConfirmState | null; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  async function ok() {
    if (!state) return;
    setBusy(true);
    try {
      await state.run();
      onClose();
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={!!state}
      onClose={onClose}
      width={420}
      icon={<span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-red/10 text-red"><AlertTriangle className="size-4" /></span>}
      title={state?.title}
      description={state?.desc}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button variant="danger" onClick={ok} disabled={busy} data-autofocus>
            {busy ? '处理中…' : state?.okText}
          </Button>
        </>
      }
    />
  );
}
