import type { KbFile } from '@/types';

export type ChunkKind = 'text' | 'table' | 'image';

export interface Chunk {
  id: string;
  index: number;
  kind: ChunkKind;
  section: string;
  page: number;
  tokens: number;
  text: string;
  overlap: number;
  table?: string[][];
  imageCaption?: string;
  /** 原文中图片的标题，用于原文预览 */
  imageTitle?: string;
  visionModel?: string;
}

/** 设计稿中第 11–12 页的示例分块（C6） */
const designed: Omit<Chunk, 'id'>[] = [
  {
    index: 30,
    kind: 'text',
    section: '4. 多模态解析',
    page: 11,
    tokens: 386,
    overlap: 32,
    text: '本章节描述 Q3 新增的多模态解析能力，目标是让扫描件、截图与图表内容也能被检索命中，并在回答中给出可追溯的原文位置。解析链路复用现有的版面分析结果，对无法直接抽取文字的区域调用 OCR 与视觉模型补全。',
  },
  {
    index: 31,
    kind: 'text',
    section: '4. 多模态解析',
    page: 12,
    tokens: 428,
    overlap: 32,
    text: '新增扫描件 OCR 管线与图片语义理解，目标 10 月中旬灰度，覆盖 PDF 扫描件、截图与流程图等常见资料类型。灰度期间仅对「产品知识库」「技术文档库」开放。',
  },
  {
    index: 32,
    kind: 'table',
    section: '4.1 表格增强',
    page: 12,
    tokens: 196,
    overlap: 0,
    text: '资料类型与解析方式对照表',
    table: [
      ['资料类型', '解析方式', '负责人'],
      ['扫描件', 'OCR + 版面还原', '王蕾'],
      ['流程图', '视觉模型描述', '刘洋'],
    ],
  },
  {
    index: 33,
    kind: 'image',
    section: '4.1 表格增强',
    page: 12,
    tokens: 312,
    overlap: 0,
    imageCaption: '图 4-1',
    imageTitle: '多模态解析流程',
    visionModel: 'Qwen-VL-Max',
    text: '多模态解析流程图：文件上传后依次经过版面分析、OCR 识别、视觉模型描述，最终分块写入知识库。',
  },
];

const sections = ['1. 背景与目标', '2. 用户场景', '3. 功能范围', '4. 多模态解析', '5. 里程碑', '6. 风险与依赖'];
const fillers = [
  '本节梳理当前资料检索中的主要痛点：跨文档查找成本高、扫描件无法命中、回答缺少可追溯来源。',
  '面向产品、研发与客服三类角色，分别整理高频提问与期望的回答形式，作为召回评测的基准集。',
  '版本范围包含知识库管理、解析配置、对话问答与引用溯源四个模块，暂不包含团队协作能力。',
  '里程碑按双周迭代推进，每个迭代结束时在内部知识库上完成一次端到端回归，记录召回率与满意度。',
  '主要依赖为向量模型服务与 OCR 服务的稳定性；若 OCR 超时比例过高，将降级为仅文本解析。',
];

/** 无分块时（如解析失败）原文预览使用的示例内容 */
export const samplePageChunks: Chunk[] = designed.filter((c) => c.page === 12).map((c) => ({ ...c, id: `sample_${c.index}` }));

export function pageCount(file: KbFile): number {
  return Math.max(3, Math.ceil(file.chunkCount / 2.7));
}

/** 为已完成文件生成确定性的 Mock 分块；产品需求文档使用设计稿内容 */
export function chunksFor(file: KbFile): Chunk[] {
  const total = file.chunkCount;
  if (!total) return [];
  const pages = pageCount(file);
  const out: Chunk[] = [];
  for (let i = 1; i <= total; i++) {
    const d = designed.find((c) => c.index === i);
    if (d && file.chunkCount >= 33) {
      out.push({ ...d, id: `chk_${file.id}_${i}` });
      continue;
    }
    const kind: ChunkKind = i % 11 === 0 ? 'table' : i % 14 === 0 ? 'image' : 'text';
    const page = Math.min(pages, Math.max(1, Math.ceil((i / total) * pages)));
    const base = fillers[i % fillers.length];
    out.push({
      id: `chk_${file.id}_${i}`,
      index: i,
      kind,
      section: sections[Math.min(sections.length - 1, Math.floor((i / total) * sections.length))],
      page,
      tokens: 180 + ((i * 37) % 300),
      overlap: kind === 'text' ? 32 : 0,
      text: kind === 'image' ? '示意图：按模块展示解析链路与数据流向，由视觉模型生成文字描述以便检索。' : base,
      table:
        kind === 'table'
          ? [
              ['模块', '负责人', '状态'],
              ['知识库管理', '陈默', '已完成'],
              ['引用溯源', '刘洋', '进行中'],
            ]
          : undefined,
      imageCaption: kind === 'image' ? `图 ${Math.ceil(i / 14)}-1` : undefined,
      visionModel: kind === 'image' ? 'Qwen-VL-Max' : undefined,
    });
  }
  // 设计稿中第 12 页仅包含 #31–#33
  if (file.chunkCount >= 33) {
    out.forEach((c) => {
      if (c.page === 12 && (c.index < 31 || c.index > 33)) c.page = c.index < 31 ? 11 : 13;
    });
  }
  return out;
}
