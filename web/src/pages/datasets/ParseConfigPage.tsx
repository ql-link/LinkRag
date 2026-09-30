import { Brain, Code, Info, Layers, RefreshCw, ScanText, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/Breadcrumb';
import { Button } from '@/components/ui/Button';
import { Segmented } from '@/components/ui/Segmented';
import { ModelSelect } from '@/components/ui/Select';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import {
  CHAT_MODELS,
  clone,
  DEFAULT_CONFIG,
  diffKeys,
  loadConfig,
  saveConfig,
  validateConfig,
  VISION_MODELS,
  type ParseConfig,
} from '@/mock/parseConfig';
import { fileCount } from '@/services/datasets';
import { useStore } from '@/services/useStore';

import { ConfigCard, MultiToggle, NumberInput, ParamRow, Slider } from './components/ConfigControls';

type SectionId = 'embedding' | 'chunking' | 'markdown' | 'pdf' | 'recall';

const SECTION_FIELDS: Record<SectionId, string[]> = {
  embedding: [],
  chunking: ['chunkMaxTokens', 'chunkOverlap', 'chunkMinTokens', 'forceSplitTokens', 'headingLevel', 'resplitLong', 'structuredOverlap'],
  markdown: ['imageEnhance', 'imageModel', 'tableEnhance', 'tableModel', 'headingRebuild'],
  pdf: ['pdfParser'],
  recall: ['channels', 'weights', 'rerank', 'contextBudget'],
};

const inSection = (key: string, s: SectionId) => SECTION_FIELDS[s].some((f) => key === f || key.startsWith(`${f}.`));

/** C8 分块与解析 / C9 增强与召回 */
export default function ParseConfigPage() {
  const { datasetId = '' } = useParams();
  const toast = useToast();
  const dataset = useStore((s) => s.datasets.find((d) => d.id === datasetId));
  const files = useStore(() => fileCount(datasetId));

  const [saved, setSaved] = useState<ParseConfig>(() => loadConfig(datasetId));
  const [cfg, setCfg] = useState<ParseConfig>(() => loadConfig(datasetId));
  const [active, setActive] = useState<SectionId>('embedding');
  const [saving, setSaving] = useState(false);
  const mainRef = useRef<HTMLDivElement>(null);

  const changed = useMemo(() => diffKeys(cfg, saved), [cfg, saved]);
  const fromDefault = useMemo(() => diffKeys(cfg, DEFAULT_CONFIG), [cfg]);
  const errors = useMemo(() => validateConfig(cfg), [cfg]);
  const errorCount = Object.keys(errors).length;
  const isMod = (k: string) => fromDefault.some((d) => d === k || d.startsWith(`${k}.`));
  const sectionMods = (s: SectionId) => SECTION_FIELDS[s].filter((f) => isMod(f)).length;
  const sectionErrors = (s: SectionId) => Object.keys(errors).filter((k) => inSection(k, s)).length;

  const set = <K extends keyof ParseConfig>(k: K, v: ParseConfig[K]) => setCfg((c) => ({ ...c, [k]: v }));

  // 离开页面前提示未保存修改
  useEffect(() => {
    if (!changed.length) return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, [changed.length]);

  // 滚动时同步左侧高亮
  useEffect(() => {
    const root = mainRef.current;
    if (!root || typeof IntersectionObserver === 'undefined') return;
    const obs = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActive(top.target.id as SectionId);
      },
      { root, rootMargin: '0px 0px -70% 0px' },
    );
    root.querySelectorAll('section[id]').forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, []);

  if (!dataset) {
    return (
      <p className="py-24 text-center text-[13px] text-muted">
        知识库不存在。
        <Link to="/datasets" className="ml-1 text-ink underline">
          返回知识库列表
        </Link>
      </p>
    );
  }

  const jump = (id: SectionId) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const save = async () => {
    if (errorCount) return;
    setSaving(true);
    await saveConfig(dataset.id, cfg);
    setSaved(clone(cfg));
    setSaving(false);
    toast('解析配置已保存，新上传或重新解析的文件将使用新配置', { tone: 'success' });
  };

  const modChip = (n: number) => (n ? <span className="rounded-[5px] bg-amber/10 px-[7px] py-[3px] text-[10.5px] leading-none font-medium text-amber">{n} 项已修改</span> : null);

  const nav: { id: SectionId; icon: ReactNode; label: string; meta: ReactNode }[] = [
    { id: 'embedding', icon: <Brain />, label: '向量模型', meta: '已绑定' },
    { id: 'chunking', icon: <Layers />, label: '分块策略', meta: `${SECTION_FIELDS.chunking.length} 项` },
    { id: 'markdown', icon: <Code />, label: 'Markdown 增强', meta: `${SECTION_FIELDS.markdown.length} 项` },
    { id: 'pdf', icon: <ScanText />, label: 'PDF 解析', meta: '1 项' },
    { id: 'recall', icon: <Search />, label: '召回检索', meta: `${SECTION_FIELDS.recall.length} 项` },
  ];

  const channelKeys = (['bm25', 'sparse', 'dense'] as const).filter((k) => cfg.channels[k]);
  const channelLabel = { bm25: 'BM25', sparse: 'Sparse', dense: 'Dense' } as const;

  return (
    <div className="relative flex h-full min-h-[640px] flex-col">
      <header className="flex h-24 shrink-0 flex-col justify-center gap-1.5 border-b border-divider pr-8 pl-10">
        <div className="text-[11px]">
          <Breadcrumb items={[{ label: '知识库', to: '/datasets' }, { label: dataset.name, to: `/datasets/${dataset.id}` }, { label: '解析配置' }]} />
        </div>
        <h1 className="font-serif text-[26px] leading-tight font-semibold text-ink">解析配置</h1>
        <p className="text-[12.5px] text-text2">调整后对新上传或重新解析的文件生效；已解析的 {files} 个文件不会自动更新。</p>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav aria-label="配置分组" className="flex w-[220px] shrink-0 flex-col gap-0.5 border-r border-divider pt-6 pr-3 pl-6">
          <p className="mb-2 text-[10.5px] text-muted">配置分组</p>
          {nav.map((n) => {
            const errs = sectionErrors(n.id);
            const mods = sectionMods(n.id);
            return (
              <button
                key={n.id}
                type="button"
                onClick={() => jump(n.id)}
                aria-current={active === n.id}
                className={cn(
                  'flex items-center gap-[9px] rounded-lg px-2.5 py-2 text-left text-[12.5px] [&>svg]:size-[13px] [&>svg]:text-text2',
                  active === n.id ? 'bg-soft font-medium text-ink' : 'text-text2 hover:bg-soft/60',
                )}
              >
                {n.icon}
                <span className="flex-1">{n.label}</span>
                {errs ? (
                  <span className="rounded-[5px] bg-red/10 px-1.5 py-0.5 text-[10.5px] leading-none font-medium text-red">{errs} 错误</span>
                ) : mods ? (
                  <span aria-label={`${mods} 项已修改`} className="size-1.5 rounded-full bg-amber" />
                ) : (
                  <span className="text-[10.5px] font-normal text-faint">{n.meta}</span>
                )}
              </button>
            );
          })}
          <div className="mt-5 flex flex-col gap-1.5 rounded-[10px] bg-soft px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-[11.5px] font-medium text-ink">
              <Info aria-hidden className="size-3" />
              生效范围
            </p>
            <p className="text-[10.5px] leading-4 text-text2">保存后，新文件使用新配置；如需让已有文件生效，请在文件列表中「全部解析」。</p>
          </div>
        </nav>

        <div ref={mainRef} className="min-w-0 flex-1 overflow-y-auto px-10 pt-6 pb-32">
          <div className="mx-auto flex w-full max-w-[960px] flex-col gap-3.5">
            <ConfigCard
              id="embedding"
              icon={<Brain />}
              title="向量模型"
              en="Embedding"
              description="绑定召回使用的向量模型，创建后不可修改"
              chip={<span className="rounded-[5px] bg-muted/10 px-[7px] py-[3px] text-[10.5px] leading-none font-medium text-muted">已绑定，不可修改</span>}
            >
              <ParamRow label="稠密向量模型">
                <ModelSelect locked size="sm" value={dataset.denseModel} options={[]} className="w-[220px]" ariaLabel="稠密向量模型" />
              </ParamRow>
              <ParamRow label="稀疏向量模型">
                <ModelSelect locked size="sm" value={dataset.sparseModel} options={[]} className="w-[220px]" ariaLabel="稀疏向量模型" />
              </ParamRow>
            </ConfigCard>

            <ConfigCard id="chunking" icon={<Layers />} title="分块策略" en="Chunking" description="控制文档切片粒度、重叠范围和超长内容处理方式" chip={modChip(sectionMods('chunking'))}>
              <ParamRow
                label="目标片段上限"
                help="期望生成的片段长度上限，影响召回粒度和上下文密度"
                modified={isMod('chunkMaxTokens')}
                note={errors.chunkMaxTokens ?? (isMod('chunkMaxTokens') ? `默认 ${DEFAULT_CONFIG.chunkMaxTokens} · 范围 256–2048` : undefined)}
                noteTone={errors.chunkMaxTokens ? 'red' : 'amber'}
              >
                <NumberInput label="目标片段上限" value={cfg.chunkMaxTokens} step={64} min={0} unit="Token" modified={isMod('chunkMaxTokens')} invalid={!!errors.chunkMaxTokens} onChange={(v) => set('chunkMaxTokens', v)} />
              </ParamRow>
              <ParamRow label="片段重叠 Token" help="相邻片段之间保留的重复 Token 数，用于降低上下文断裂" modified={isMod('chunkOverlap')}>
                <Slider label="片段重叠 Token" min={0} max={256} value={cfg.chunkOverlap} onChange={(v) => set('chunkOverlap', v)} />
              </ParamRow>
              <ParamRow label="候选片段最小 Token" help="单个候选片段的最小 Token 数，过小会增加碎片化" modified={isMod('chunkMinTokens')} note={errors.chunkMinTokens} noteTone="red">
                <NumberInput label="候选片段最小 Token" value={cfg.chunkMinTokens} step={32} min={0} unit="Token" modified={isMod('chunkMinTokens')} invalid={!!errors.chunkMinTokens} onChange={(v) => set('chunkMinTokens', v)} />
              </ParamRow>
              <ParamRow label="强制拆分上限" help="超过该上限的片段会被强制拆分" modified={isMod('forceSplitTokens')} note={errors.forceSplitTokens} noteTone="red">
                <NumberInput label="强制拆分上限" value={cfg.forceSplitTokens} step={128} min={0} unit="Token" modified={isMod('forceSplitTokens')} invalid={!!errors.forceSplitTokens} onChange={(v) => set('forceSplitTokens', v)} />
              </ParamRow>
              <ParamRow label="标题分块层级" help="解析标题结构时保留到的最大层级" modified={isMod('headingLevel')}>
                <Segmented
                  ariaLabel="标题分块层级"
                  value={String(cfg.headingLevel)}
                  onChange={(v) => set('headingLevel', Number(v) as ParseConfig['headingLevel'])}
                  options={[1, 2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `H${n}` }))}
                />
              </ParamRow>
              <ParamRow label="超长片段再切分" help="超长片段按语义连续性细分，减少单个片段过长" modified={isMod('resplitLong')}>
                <Switch label="超长片段再切分" checked={cfg.resplitLong} onChange={(v) => set('resplitLong', v)} />
              </ParamRow>
              <ParamRow label="结构化内容参与重叠" help="表格、代码块、公式等参与相邻片段的重叠保留" modified={isMod('structuredOverlap')}>
                <Switch label="结构化内容参与重叠" checked={cfg.structuredOverlap} onChange={(v) => set('structuredOverlap', v)} />
              </ParamRow>
            </ConfigCard>

            <ConfigCard id="markdown" icon={<Code />} title="Markdown 增强" en="Enhancement" description="为表格、图片和标题结构补充可检索信息" chip={modChip(sectionMods('markdown'))}>
              <ParamRow label="图片增强" help="使用视觉模型为图片生成文本描述" modified={isMod('imageEnhance') || isMod('imageModel')}>
                <ModelSelect size="sm" value={cfg.imageModel} options={VISION_MODELS} onChange={(v) => set('imageModel', v)} className={cn('w-[180px]', !cfg.imageEnhance && 'opacity-50')} ariaLabel="图片增强模型" />
                <Switch label="图片增强" checked={cfg.imageEnhance} onChange={(v) => set('imageEnhance', v)} />
              </ParamRow>
              <ParamRow label="表格增强" help="使用对话模型为表格补充语义描述" modified={isMod('tableEnhance') || isMod('tableModel')}>
                <ModelSelect size="sm" value={cfg.tableModel} options={CHAT_MODELS} onChange={(v) => set('tableModel', v)} className={cn('w-[180px]', !cfg.tableEnhance && 'opacity-50')} ariaLabel="表格增强模型" />
                <Switch label="表格增强" checked={cfg.tableEnhance} onChange={(v) => set('tableEnhance', v)} />
              </ParamRow>
              <ParamRow label="标题层级重建" help="根据文档样式还原标题层级" modified={isMod('headingRebuild')}>
                <Switch label="标题层级重建" checked={cfg.headingRebuild} onChange={(v) => set('headingRebuild', v)} />
              </ParamRow>
            </ConfigCard>

            <ConfigCard id="pdf" icon={<ScanText />} title="PDF 解析" en="PDF Parser" description="选择 PDF 文档解析方案" chip={modChip(sectionMods('pdf'))}>
              <ParamRow label="PDF 解析方案" help="MinerU 适合版式复杂的文档；扫描件较多时可选 OpenDataLoader" modified={isMod('pdfParser')}>
                <Segmented
                  ariaLabel="PDF 解析方案"
                  value={cfg.pdfParser}
                  onChange={(v) => set('pdfParser', v)}
                  options={(['MinerU', 'OpenDataLoader', 'Naive'] as const).map((p) => ({ value: p, label: p }))}
                />
              </ParamRow>
            </ConfigCard>

            <ConfigCard id="recall" icon={<Search />} title="召回检索" en="Recall" description="检索通道、融合权重、候选数量与上下文预算" chip={modChip(sectionMods('recall'))}>
              <ParamRow label="启用召回路" help="通道越多覆盖面越广，也更依赖融合排序质量" modified={isMod('channels')} note={errors.channels} noteTone="red">
                <MultiToggle
                  label="启用召回路"
                  value={cfg.channels}
                  onChange={(v) => set('channels', v)}
                  options={[
                    { key: 'bm25', label: 'BM25' },
                    { key: 'sparse', label: 'Sparse' },
                    { key: 'dense', label: 'Dense' },
                  ]}
                />
              </ParamRow>
              {channelKeys.length > 0 && (
                <ParamRow label="融合权重" help="按通道设置融合排序时的权重" modified={isMod('weights')} note={errors.weights} noteTone="red">
                  <div className="flex gap-2">
                    {channelKeys.map((k) => (
                      <div key={k} className="flex flex-col gap-[3px]">
                        <span className="text-[10px] font-medium text-muted">{channelLabel[k]}</span>
                        <NumberInput
                          label={`${channelLabel[k]} 权重`}
                          value={cfg.weights[k]}
                          step={0.1}
                          min={0}
                          max={1}
                          decimals={1}
                          invalid={!!errors.weights}
                          modified={isMod(`weights.${k}`)}
                          onChange={(v) => set('weights', { ...cfg.weights, [k]: v })}
                        />
                      </div>
                    ))}
                  </div>
                </ParamRow>
              )}
              <ParamRow label="启用重排" help="使用 bge-reranker-v2 对候选组内重排 · 候选 20 条" modified={isMod('rerank')}>
                <Switch label="启用重排" checked={cfg.rerank} onChange={(v) => set('rerank', v)} />
              </ParamRow>
              <ParamRow
                label="生成上下文 Token 预算"
                help="生成回答时可使用的上下文上限 · 范围 1,000–16,000"
                modified={isMod('contextBudget')}
                note={errors.contextBudget}
                noteTone="red"
              >
                <NumberInput label="生成上下文 Token 预算" value={cfg.contextBudget} step={512} min={0} unit="Token" modified={isMod('contextBudget')} invalid={!!errors.contextBudget} onChange={(v) => set('contextBudget', v)} />
              </ParamRow>
            </ConfigCard>
          </div>
        </div>
      </div>

      {(changed.length > 0 || errorCount > 0) && (
        <div role="region" aria-label="保存修改" className="absolute bottom-[25px] left-[calc(50%+110px)] flex w-[600px] -translate-x-1/2 items-center gap-2.5 rounded-xl border border-line bg-white py-[9px] pr-2.5 pl-4 shadow-[0_8px_28px_0_rgba(0,0,0,0.12)]">
          <span className={cn('size-[7px] rounded-full', errorCount ? 'bg-red' : 'bg-amber')} />
          <span className="text-[12.5px] font-medium text-ink">
            有 {changed.length} 项未保存的修改{errorCount ? ` · ${errorCount} 项需修正` : ''}
          </span>
          <span className="flex-1" />
          <Button variant="secondary" icon={<RefreshCw className="size-3" />} onClick={() => setCfg(clone(DEFAULT_CONFIG))}>
            恢复默认
          </Button>
          <Button variant="secondary" onClick={() => setCfg(clone(saved))}>
            放弃修改
          </Button>
          <Button onClick={save} disabled={!!errorCount || saving || !changed.length} className="disabled:opacity-40">
            {saving ? '保存中…' : '保存配置'}
          </Button>
        </div>
      )}
    </div>
  );
}
