import { usageApi } from '@/api/endpoints';
import { USE_MOCK } from '@/api/http';
import { db } from '@/mock/db';
import { seedConversationTotal, seedRecentFileIds } from '@/mock/seed';

import { conversationSummaries } from './chat';
import { fileCount, fileStats } from './datasets';
import { formatCompact, presetRange } from './usage';

/**
 * 首页工作台服务（B1 / B2）。统计数据在接入 Java 接口后由后端聚合返回，
 * 当前从 Mock 状态计算；页面只依赖这里导出的函数。
 */

const ONBOARD_KEY = 'linkrag.onboarding';

export interface OnboardingState {
  /** 注册后首次进入，展示三步引导（B1） */
  fresh: boolean;
  skipped: boolean;
  /** 已接入模型厂商（模型配置阶段上线前以本地标记模拟） */
  modelReady: boolean;
  /** 注册时的知识库数量，之后新建即视为完成第 2 步 */
  baseDatasets: number;
  chatted: boolean;
}

const initial: OnboardingState = { fresh: false, skipped: false, modelReady: false, baseDatasets: 0, chatted: false };

export function onboarding(): OnboardingState {
  try {
    const raw = localStorage.getItem(ONBOARD_KEY);
    return raw ? { ...initial, ...JSON.parse(raw) } : initial;
  } catch {
    return initial;
  }
}

export function saveOnboarding(patch: Partial<OnboardingState>) {
  localStorage.setItem(ONBOARD_KEY, JSON.stringify({ ...onboarding(), ...patch }));
}

/** 注册成功后调用：开启新用户引导 */
export function startOnboarding() {
  localStorage.setItem(ONBOARD_KEY, JSON.stringify({ ...initial, fresh: true, baseDatasets: db.state.datasets.length }));
}

/** 三步引导完成情况：接入模型 → 创建知识库 → 发起对话 */
export function onboardingSteps() {
  const s = onboarding();
  return { model: s.modelReady, dataset: db.state.datasets.length > s.baseDatasets, chat: s.chatted };
}

/** 刚注册、未跳过且三步未全部完成时展示 B1，否则展示日常工作台 B2 */
export function showOnboarding() {
  const s = onboarding();
  const steps = onboardingSteps();
  return s.fresh && !s.skipped && !(steps.model && steps.dataset && steps.chat);
}

export function overview() {
  const { datasets } = db.state;
  const files = datasets.reduce((n, d) => n + fileCount(d.id), 0);
  const parsing = datasets.reduce((n, d) => n + fileStats(d.id).parsing, 0);
  return {
    conversations: USE_MOCK
      ? { total: seedConversationTotal, weekDelta: 12 }
      : { total: conversationSummaries().length, weekDelta: conversationSummaries().filter((c) => /今天|昨天|刚刚/.test(c.updatedAt)).length },
    datasets: { total: datasets.length, updated: datasets.filter((d) => /今天|昨天|刚刚/.test(d.updatedAt)).length + (USE_MOCK ? 1 : 0) },
    files: { total: files, parsing },
  };
}

export interface WeekTokens {
  total: string;
  /** 较上周变化，如「+18%」；上周无数据时为 undefined */
  delta?: string;
}

/** 概览卡片「7 天 Token」：真实模式取用量接口近 7 天汇总与环比（与「用量」页近 7 天口径一致） */
export async function weekTokens(): Promise<WeekTokens> {
  if (USE_MOCK) return { total: '1.28M', delta: '+18%' };
  const { from, to } = presetRange('7d');
  const q = { startDate: from, endDate: to, stage: 'all' };
  const [summary, trend] = await Promise.all([usageApi.summary(q), usageApi.trend(q)]);
  const rate = trend.previousCalls ? trend.tokenGrowthRate : null;
  return {
    total: formatCompact(summary.totalTokens),
    delta: rate == null ? undefined : `${rate >= 0 ? '+' : ''}${Math.round(rate * 100)}%`,
  };
}

/** 最近一次对话（「继续上次对话」卡片） */
export function lastConversation() {
  const c = conversationSummaries()[0];
  if (!c) return undefined;
  const dataset = db.state.datasets.find((d) => d.id === c.datasetId);
  return dataset ? { conversation: c, dataset } : undefined;
}

/** 最近资料：优先设计稿指定的文件，不足时按列表顺序补齐 */
export function recentFiles(limit = 3) {
  const { files, datasets } = db.state;
  const byId = new Map(files.map((f) => [f.id, f]));
  const picked = seedRecentFileIds.map((id) => byId.get(id)).filter((f) => !!f);
  const rest = files.filter((f) => !seedRecentFileIds.includes(f.id));
  return [...picked, ...rest]
    .map((file) => ({ file, dataset: datasets.find((d) => d.id === file.datasetId) }))
    .filter((x): x is { file: typeof x.file; dataset: NonNullable<typeof x.dataset> } => !!x.dataset)
    .slice(0, limit);
}
