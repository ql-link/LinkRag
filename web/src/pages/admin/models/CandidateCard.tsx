/** D2 单个候选模型卡片（按模型名聚合多个能力） */
import { Chip, type Tone } from '@/components/ui/Chip';
import { Button } from '@/components/ui/Button';

import { Card, fmt, relTime } from '../ui';
import type { ReviewStatus, SyncCandidate } from './api';
import { parseModalities, type CandidateGroup } from './helpers';
import { CapChip } from './shared';

const REVIEW: Record<ReviewStatus, { label: string; tone: Tone }> = {
  PENDING: { label: '待审核', tone: 'amber' },
  PUBLISHED: { label: '已发布', tone: 'green' },
  REJECTED: { label: '已拒绝', tone: 'gray' },
};

/** 组状态：有待审核即为待审核，否则全部已发布为已发布，否则已拒绝 */
export function groupStatus(items: SyncCandidate[]): ReviewStatus {
  if (items.some((c) => c.reviewStatus === 'PENDING')) return 'PENDING';
  if (items.every((c) => c.reviewStatus === 'PUBLISHED')) return 'PUBLISHED';
  return 'REJECTED';
}

interface Props {
  group: CandidateGroup;
  busy: boolean;
  onMeta: (c: SyncCandidate) => void;
  onPublish: () => void;
  onReject: () => void;
  onRestore: () => void;
}

export function CandidateCard({ group, busy, onMeta, onPublish, onReject, onRestore }: Props) {
  const first = group.items[0];
  const status = groupStatus(group.items);
  const existing = group.items.filter((c) => c.matchedProviderModelId !== null).length;
  const num = (n: number | null) => (n === null || n === undefined ? '—' : fmt(n));
  const lastSeen = group.items.reduce((m, c) => (c.lastSeenAt > m ? c.lastSeenAt : m), first.lastSeenAt);
  const meta: [string, string][] = [
    ['发布日期', first.releaseDate ?? '—'],
    ['上下文窗口', num(first.contextWindow)],
    ['最大输出', num(first.maxOutputTokens)],
    ['输入模态', parseModalities(first.inputModalities).join(', ') || '—'],
    ['输出模态', parseModalities(first.outputModalities).join(', ') || '—'],
    ['最后发现', relTime(lastSeen)],
  ];

  return (
    <Card className="px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-num text-[13px] font-medium text-ink">{group.modelName}</span>
        <Chip tone={REVIEW[status].tone}>{REVIEW[status].label}</Chip>
        {group.items.map((c) => (
          <CapChip key={c.id} cap={c.capability} />
        ))}
        <Chip tone={existing ? 'blue' : 'gray'} dot={false}>
          {existing ? `${existing}/${group.items.length} 已存在` : '新增'}
        </Chip>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" onClick={() => onMeta(first)}>
            元数据
          </Button>
          {status === 'PENDING' && (
            <>
              <Button variant="secondary" onClick={onReject} disabled={busy}>
                拒绝
              </Button>
              <Button onClick={onPublish} disabled={busy}>
                发布
              </Button>
            </>
          )}
          {status === 'REJECTED' && (
            <Button variant="secondary" onClick={onRestore} disabled={busy}>
              恢复
            </Button>
          )}
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-6 gap-3">
        {meta.map(([k, v]) => (
          <div key={k} className="flex min-w-0 flex-col gap-1">
            <dt className="text-[11px] text-muted">{k}</dt>
            <dd className="truncate font-num text-[12px] text-ink" title={v}>
              {v}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
