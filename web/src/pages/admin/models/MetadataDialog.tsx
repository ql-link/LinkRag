/** D9 原始元数据 */
import { Copy } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { useToast } from '@/contexts/ToastContext';

import { StateFeedback } from '../StateFeedback';
import { relTime } from '../ui';
import type { SyncCandidate } from './api';
import { prettyMetadata } from './helpers';

export function MetadataDialog({ candidate, onClose }: { candidate: SyncCandidate | null; onClose: () => void }) {
  const toast = useToast();
  const text = candidate ? prettyMetadata(candidate.rawMetadata) : '';
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      toast('已复制', { tone: 'success' });
    } catch {
      toast('复制失败，请手动选择文本', { tone: 'error' });
    }
  }
  return (
    <Dialog
      open={!!candidate}
      onClose={onClose}
      width={600}
      title="原始元数据"
      description={candidate && `${candidate.externalModelId || candidate.modelName} · ${candidate.syncSource === 'MODELS_DEV' ? 'models.dev' : candidate.syncSource} · ${relTime(candidate.lastSeenAt)}`}
      footer={
        <Button variant="secondary" icon={<Copy className="size-3.5" />} onClick={copy} disabled={!text}>
          复制
        </Button>
      }
    >
      {text ? (
        <pre className="max-h-[420px] overflow-auto rounded-[10px] bg-soft p-4 font-num text-[11.5px] leading-[1.6] whitespace-pre-wrap text-ink">{text}</pre>
      ) : (
        <StateFeedback kind="empty" title="没有原始元数据" />
      )}
    </Dialog>
  );
}
