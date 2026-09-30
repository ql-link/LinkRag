import { Trash2 } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { useToast } from '@/contexts/ToastContext';
import { deleteConversation, roundsOf, type Conversation } from '@/services/chat';

/** F7 删除对话：二次确认，知识库与文件不受影响 */
export function DeleteConversationDialog({ conversation, onClose, onDeleted }: { conversation: Conversation | null; onClose: () => void; onDeleted?: (c: Conversation) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!conversation) return null;

  const confirm = async () => {
    setBusy(true);
    await deleteConversation(conversation.id);
    setBusy(false);
    toast(`已删除「${conversation.title}」`, { tone: 'success' });
    onDeleted?.(conversation);
    onClose();
  };

  return (
    <Dialog
      open
      onClose={onClose}
      width={440}
      icon={
        <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-red/10 text-red">
          <Trash2 aria-hidden className="size-4" />
        </span>
      }
      title={`删除对话「${conversation.title}」？`}
      description={`将删除这个对话的 ${roundsOf(conversation)} 轮问答和引用记录，删除后无法恢复。知识库和文件不受影响。`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button variant="danger" data-autofocus onClick={confirm} disabled={busy}>
            删除对话
          </Button>
        </>
      }
    />
  );
}
