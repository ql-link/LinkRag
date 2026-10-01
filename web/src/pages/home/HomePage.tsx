import { ArrowRight, ChartColumn, Check, Database, FileText, MessageSquare, Plus } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { DocCard } from '@/components/DocIllustration';
import { TypeTag } from '@/components/FileBadge';
import { SectionLabel } from '@/components/SectionLabel';
import { Button } from '@/components/ui/Button';
import { PageLoading } from '@/components/ui/Loading';
import { usePageLoad } from '@/lib/usePageLoad';
import { useAuth } from '@/contexts/AuthContext';
import { useSearch } from '@/contexts/SearchContext';
import { PageColumn } from '@/layouts/AppLayout';
import { cn } from '@/lib/cn';
import { useElementWidth } from '@/lib/useElementWidth';
import { CreateDatasetDialog } from '@/pages/datasets/components/CreateDatasetDialog';
import { lastConversation, onboardingSteps, overview, recentFiles, saveOnboarding, showOnboarding, weekTokens, type WeekTokens } from '@/services/home';
import { useStore } from '@/services/useStore';
import type { KbFile } from '@/types';

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

function greeting(d: Date) {
  const h = d.getHours();
  if (h < 5) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 13) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

/** 首页顶部：日期眉标 + 问候 + 右侧文字操作 */
function HomeHeader({ description, actions }: { description: string; actions: ReactNode }) {
  const { user } = useAuth();
  const now = new Date();
  return (
    <>
      <header className="flex items-start gap-4">
        <div className="flex min-w-0 flex-col">
          <p className="text-[11px] leading-none text-muted">
            工作台 · {now.getMonth() + 1} 月 {now.getDate()} 日 {WEEKDAYS[now.getDay()]}
          </p>
          <h1 className="mt-2 font-serif text-[28px] leading-[1.35] font-semibold text-ink">
            {greeting(now)}，{user?.displayName}
          </h1>
          <p className="mt-1.5 text-[13px] leading-none text-text2">{description}</p>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-3.5 text-[11.5px] text-text2">{actions}</div>
      </header>
      <div className="mt-6 mb-7 h-px bg-divider" />
    </>
  );
}

/** 横向大卡片：左侧 244×176 插画舞台 + 右侧信息 */
function StageCard({ stage, eyebrow, title, description, footer }: { stage: ReactNode; eyebrow: string; title: string; description: string; footer: ReactNode }) {
  return (
    <section className="flex h-[190px] gap-7 rounded-2xl border border-line bg-white py-[7px] pr-6 pl-[7px] shadow-card">
      <div aria-hidden className="relative h-[176px] w-[244px] shrink-0 overflow-hidden rounded-[11px] bg-soft">
        {stage}
      </div>
      <div className="flex min-w-0 flex-1 flex-col pt-[22px] pb-2.5">
        <p className="text-[11px] text-muted">{eyebrow}</p>
        <h2 className="mt-2 truncate font-serif text-[19px] font-semibold text-ink">{title}</h2>
        <p className="mt-2.5 truncate text-[13px] text-text2">{description}</p>
        <div className="flex-1" />
        <div className="flex items-center gap-3">{footer}</div>
      </div>
    </section>
  );
}

/** 进度短条：已完成段为墨色（B1 为前 n 段，B2 为最后一段表示当前轮） */
function Segments({ total, filled, className }: { total: number; filled: (i: number) => boolean; className?: string }) {
  return (
    <div aria-hidden className={cn('flex gap-1', className)}>
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className={cn('h-[3px] w-6 rounded-[2px]', filled(i) ? 'bg-ink' : 'bg-dash')} />
      ))}
    </div>
  );
}

export default function HomePage() {
  useStore((s) => s.datasets.length);
  const [, force] = useState(0);
  return showOnboarding() ? <Onboarding onChange={() => force((n) => n + 1)} /> : <Dashboard />;
}

/* ---------------- B1 新用户引导 ---------------- */

function Onboarding({ onChange }: { onChange: () => void }) {
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const steps = onboardingSteps();
  const done = [steps.model, steps.dataset, steps.chat];
  const doneCount = done.filter(Boolean).length;
  const current = done.findIndex((d) => !d);

  /** 第 1 步在模型配置页接入厂商后自动完成 */
  const goModel = () => navigate('/models');
  const goChat = () => {
    saveOnboarding({ chatted: true });
    onChange();
    navigate('/chat');
  };
  const skip = () => {
    saveOnboarding({ skipped: true });
    onChange();
  };

  const cards = [
    { title: '接入模型厂商', desc: '填写 API Key，启用对话与向量模型', cta: '去配置', onClick: goModel },
    { title: '创建知识库', desc: '上传 PDF / Word / Markdown 等资料', cta: '新建知识库', onClick: () => setCreating(true) },
    { title: '开始对话', desc: '选择知识库提问，回答附带来源片段', cta: '新建对话', onClick: goChat },
  ];
  const primary = cards[current] ?? cards[2];

  return (
    <PageColumn>
      <HomeHeader
        description="欢迎使用 LinkRag，先完成三步设置，开始第一次检索问答。"
        actions={
          <button type="button" onClick={skip} className="hover:text-ink">
            跳过引导
          </button>
        }
      />

      <StageCard
        stage={
          <>
            <DocCard style={{ left: 88, top: 34 }} />
            <div className="absolute top-[120px] left-[62px] flex h-[34px] w-[120px] items-center rounded-[9px] border border-line bg-white pl-[27px] text-[11px] font-medium text-ink shadow-[0_6px_16px_0_rgba(0,0,0,0.08)]">
              新建知识库
            </div>
            <span className="absolute top-[112px] left-[168px] flex size-9 items-center justify-center rounded-full bg-ink shadow-[0_4px_10px_0_rgba(0,0,0,0.12)]">
              <Plus className="size-4 text-white" />
            </span>
          </>
        }
        eyebrow={`开始使用 · 第 ${Math.min(3, doneCount + 1)} / 3 步`}
        title="三步搭建你的知识空间"
        description="接入模型 → 创建知识库并上传资料 → 发起一次带引用的问答"
        footer={
          <>
            <Segments total={3} filled={(i) => done[i]} />
            <p className="text-[11px] text-muted">已完成 {doneCount} / 3</p>
            <span className="flex-1" />
            <Button trailingIcon={<ArrowRight className="size-3" />} className="pr-3.5 pl-[17px]" onClick={primary.onClick}>
              {primary.cta === '去配置' ? '配置模型' : primary.cta}
            </Button>
          </>
        }
      />

      <SectionLabel label="开始步骤" action={<span className="text-muted">预计 3 分钟</span>} className="mt-7 mb-[18px]" />
      <ol className="flex gap-4">
        {cards.map((c, i) => {
          const isDone = done[i];
          const isCurrent = i === current;
          return (
            <li key={c.title} className={cn('flex flex-1 flex-col gap-2.5 rounded-[14px] border bg-white p-[18px] shadow-card', isCurrent ? 'border-ink' : 'border-line')}>
              <span
                className={cn(
                  'flex size-6 items-center justify-center rounded-full font-num text-[11px] font-semibold',
                  isDone ? 'bg-green text-white' : isCurrent ? 'bg-ink text-white' : 'bg-soft text-text2',
                )}
              >
                {isDone ? <Check aria-label="已完成" className="size-3" strokeWidth={3} /> : i + 1}
              </span>
              <p className="text-[13.5px] font-medium text-ink">{c.title}</p>
              <p className="text-[11.5px] text-text2">{c.desc}</p>
              <button
                type="button"
                onClick={c.onClick}
                className={cn('mt-0.5 flex w-fit items-center gap-[5px] text-[12px] font-medium hover:underline', isCurrent ? 'text-ink' : 'text-muted hover:text-ink')}
              >
                {isDone ? '已完成' : c.cta}
                {!isDone && <ArrowRight aria-hidden className="size-[11px]" />}
              </button>
            </li>
          );
        })}
      </ol>

      <SectionLabel label="最近资料" className="mt-7 mb-[18px]" />
      <RecentFilesOrEmpty />

      <CreateDatasetDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(ds) => {
          onChange();
          navigate(`/datasets/${ds.id}`);
        }}
      />
    </PageColumn>
  );
}

/** 卡片最小宽度与间距，与知识库列表一致；列数随内容列宽度变化 */
const CARD_MIN = 250;
const CARD_GAP = 16;

/** 最近资料只展示一行：按当前宽度能放下几列就取几个文件，避免出现半行空位 */
function RecentFilesOrEmpty() {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const columns = Math.max(1, Math.floor((width + CARD_GAP) / (CARD_MIN + CARD_GAP)));
  const files = useStore(() => recentFiles(width ? columns : 3));
  return (
    <div ref={ref}>
      {files.length ? (
        <RecentFiles items={files} columns={columns} />
      ) : (
        <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-dashed border-dash py-9">
          <span className="flex size-10 items-center justify-center rounded-full bg-soft text-text2">
            <FileText aria-hidden className="size-[17px]" />
          </span>
          <p className="text-[13.5px] font-medium text-ink">还没有资料</p>
          <p className="text-[12px] text-muted">上传文档后会在这里快速回到最近文件。</p>
        </div>
      )}
    </div>
  );
}

/* ---------------- B2 日常工作台 ---------------- */

function Dashboard() {
  const { openPalette } = useSearch();
  const stats = useStore(() => overview());
  const last = useStore(() => lastConversation());
  const navigate = useNavigate();
  // 首屏数据由应用外壳统一装载；本页额外的用量接口返回后再整体展示。null：用量加载失败
  const [tokens, setTokens] = useState<WeekTokens | null>(null);
  const loaded = usePageLoad(async () => setTokens(await weekTokens()), [], () => setTokens(null));

  if (!loaded) return <PageLoading />;

  const statCards: { icon: ReactNode; label: string; value: string; sub: string; to?: string }[] = [
    { icon: <MessageSquare />, label: '对话', value: String(stats.conversations.total), sub: `本周 +${stats.conversations.weekDelta}` },
    { icon: <Database />, label: '知识库', value: String(stats.datasets.total), sub: `${stats.datasets.updated} 个更新`, to: '/datasets' },
    { icon: <FileText />, label: '文件', value: stats.files.total.toLocaleString('en-US'), sub: stats.files.parsing ? `${stats.files.parsing} 个解析中` : '全部已解析', to: '/datasets' },
    {
      icon: <ChartColumn />,
      label: '7 天 Token',
      value: tokens ? tokens.total : '—',
      sub: !tokens ? '用量数据加载失败' : tokens.delta ? `较上周 ${tokens.delta}` : '上周暂无用量',
      to: '/usage',
    },
  ];

  return (
    <PageColumn>
      <HomeHeader
        description="查看最近工作、资料状态和系统用量。"
        actions={
          <>
            <button type="button" onClick={() => openPalette()} className="hover:text-ink">
              搜索
            </button>
            <button type="button" onClick={() => navigate('/chat')} className="hover:text-ink">
              新建对话
            </button>
          </>
        }
      />

      {last ? (
        <StageCard
          stage={
            <>
              <div className="absolute top-[26px] left-[47px] h-[122px] w-[150px] overflow-hidden rounded-xl border border-line bg-white shadow-[0_6px_16px_0_rgba(0,0,0,0.08)]">
                <div className="flex h-[26px] items-center bg-ink pl-3 text-[10px] font-medium text-white">{last.dataset.name}</div>
                <div className="absolute top-[35px] left-[67px] h-4 w-[70px] rounded-lg bg-soft" />
                {[96, 110, 80].map((w, i) => (
                  <div key={i} style={{ top: 61 + i * 9, width: w }} className="absolute left-[11px] h-[3px] rounded-[1px] bg-divider" />
                ))}
                <div className="absolute top-[91px] left-[11px] h-2.5 w-[30px] rounded-[3px] bg-blue/15" />
                <div className="absolute top-[91px] left-[45px] h-2.5 w-[30px] rounded-[3px] bg-blue/15" />
              </div>
              <span className="absolute top-[112px] left-[176px] flex size-9 items-center justify-center rounded-full bg-blue shadow-[0_4px_10px_0_rgba(0,0,0,0.12)]">
                <MessageSquare className="size-4 text-white" />
              </span>
            </>
          }
          eyebrow={`继续上次对话 · ${last.conversation.updatedAt} · ${last.dataset.name}`}
          title={last.conversation.title}
          description={`${last.conversation.model} · 引用 ${last.conversation.citedDocs} 份文档中的 ${last.conversation.citedChunks} 个片段 · 共 ${last.conversation.rounds} 轮问答`}
          footer={
            <>
              <Segments total={last.conversation.rounds} filled={(i) => i === last.conversation.rounds - 1} />
              <p className="truncate text-[11px] text-muted">
                第 {last.conversation.rounds} / {last.conversation.rounds} 轮 · 最近回答 {last.conversation.lastAnswerChars.toLocaleString('en-US')} 字
              </p>
              <span className="flex-1" />
              <Button trailingIcon={<ArrowRight className="size-3" />} className="pr-3.5 pl-[17px]" onClick={() => navigate(`/chat/${last.conversation.id}`)}>
                继续对话
              </Button>
            </>
          }
        />
      ) : null}

      <SectionLabel label="概览" action={<span className="text-muted">近 7 天</span>} className="mt-7 mb-[18px]" />
      <div className="grid grid-cols-4 gap-4">
        {statCards.map((s) => {
          const body = (
            <>
              <span className="flex items-center gap-1.5 text-[11px] text-muted [&>svg]:size-3 [&>svg]:text-text2">
                {s.icon}
                {s.label}
              </span>
              <span className="font-num text-[24px] leading-none font-semibold text-ink">{s.value}</span>
              <span className="text-[11px] text-text2">{s.sub}</span>
            </>
          );
          const cls = 'flex flex-col gap-2.5 rounded-[14px] border border-line bg-white px-[18px] py-4 shadow-card';
          return s.to ? (
            <Link key={s.label} to={s.to} className={cn(cls, 'transition-colors hover:border-dash')}>
              {body}
            </Link>
          ) : (
            <div key={s.label} className={cls}>
              {body}
            </div>
          );
        })}
      </div>

      <SectionLabel
        label="最近资料"
        action={
          <Link to="/datasets" className="text-muted hover:text-ink">
            查看全部
          </Link>
        }
        className="mt-7 mb-[18px]"
      />
      <RecentFilesOrEmpty />
    </PageColumn>
  );
}

function fileStatusText(file: KbFile) {
  if (file.status === 'done') return '已解析';
  if (file.status === 'failed') return '解析失败';
  if (file.status === 'queued') return '排队中';
  if (file.status === 'uploading') return `上传中 ${file.progressEstimated ? '≈' : ''}${file.progress}%`;
  return `解析中 ${file.progressEstimated ? '≈' : ''}${file.progress}%`;
}

/** 最近资料卡片：文档插画 + 类型标签；解析中时底部显示进度条 */
function RecentFiles({ items, columns }: { items: ReturnType<typeof recentFiles>; columns: number }) {
  return (
    <div style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }} className="grid gap-4">
      {items.map(({ file, dataset }) => {
        const running = file.status === 'parsing' || file.status === 'uploading';
        return (
          <Link
            key={file.id}
            to={`/datasets/${dataset.id}/files/${file.id}`}
            className="flex flex-col rounded-2xl border border-line bg-white px-[7px] pt-[7px] pb-[17px] shadow-card transition-colors hover:border-dash"
          >
            <div aria-hidden className="relative h-24 overflow-hidden rounded-[11px] bg-soft">
              <div className="absolute top-0 left-1/2 h-full w-[262px] -translate-x-1/2">
                <DocCard style={{ left: 97, top: 16 }} />
                <TypeTag type={file.type} style={{ left: 151, top: 56 }} />
                {running && (
                  <>
                    <div className="absolute top-[82px] left-[71px] h-[3px] w-[120px] rounded-[2px] bg-dash" />
                    <div style={{ width: (120 * file.progress) / 100 }} className="absolute top-[82px] left-[71px] h-[3px] rounded-[2px] bg-amber transition-[width]" />
                  </>
                )}
              </div>
            </div>
            <div className="flex flex-col gap-[7px] pt-3.5 pl-3">
              <p className="truncate text-[12.5px] font-medium text-ink">{file.name}</p>
              <p className="truncate text-[11px] text-muted">
                {dataset.name} · {fileStatusText(file)} · {file.updatedAt}
              </p>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
