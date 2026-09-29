import { ProviderMark } from '@/components/ProviderMark';
import { modelIcon } from '@/services/backend';
import { providerOf, useModels } from '@/services/models';

/** Mock 模型的字母徽标兜底（真实模式优先使用所属厂商的 logo） */
const palette: Record<string, { letter: string; color: string }> = {
  'bge-m3': { letter: 'S', color: '#7a5bd0' },
  'bge-large-zh-v1.5': { letter: 'S', color: '#7a5bd0' },
  'text-embedding-3-large': { letter: 'O', color: '#1d1d1b' },
  BM25: { letter: 'L', color: '#1d1d1b' },
  SPLADE: { letter: 'S', color: '#55554f' },
  'Qwen-VL-Max': { letter: 'Q', color: '#615ced' },
  'Qwen-Max': { letter: 'Q', color: '#615ced' },
  'DeepSeek-V3': { letter: 'D', color: '#4d6bfe' },
  'GPT-4o': { letter: 'O', color: '#1d1d1b' },
};

/** 模型徽标：按模型名找到所属厂商，展示厂商 logo；找不到时回退为字母方块 */
export function ModelBadge({ model, size = 20 }: { model: string; size?: 18 | 20 }) {
  const info = useModels((s) => s.models.find((m) => m.name === model));
  const provider = useModels((s) => providerOf(info, s));
  const p = palette[model] ?? { letter: (provider?.letter ?? model.slice(0, 1)).toUpperCase(), color: provider?.color ?? '#55554f' };
  return <ProviderMark letter={p.letter} color={p.color} iconUrl={info ? modelIcon(info.id, provider) : provider?.iconUrl} size={size} />;
}

