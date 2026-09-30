import type { Dataset, FileType, KbFile } from '@/types';

import { seedDatasets, seedFiles, seedHiddenFileCounts } from './seed';

/**
 * 内存 Mock 数据库：模拟后端状态与异步进度（上传 → 排队 → 解析 → 完成）。
 * 通过 subscribe/getVersion 接入 useSyncExternalStore，页面自动刷新。
 */
interface State {
  datasets: Dataset[];
  files: KbFile[];
  hiddenCounts: Record<string, number>;
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

let state: State = {
  datasets: clone(seedDatasets),
  files: clone(seedFiles),
  hiddenCounts: { ...seedHiddenFileCounts },
};
let version = 0;
const listeners = new Set<() => void>();

function emit() {
  version += 1;
  listeners.forEach((l) => l());
}

export const db = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getVersion: () => version,
  get state() {
    return state;
  },
  update(mutator: (draft: State) => void) {
    const draft = { ...state, datasets: [...state.datasets], files: [...state.files], hiddenCounts: { ...state.hiddenCounts } };
    mutator(draft);
    state = draft;
    emit();
  },
  /** 仅供测试：恢复种子数据 */
  reset() {
    state = { datasets: clone(seedDatasets), files: clone(seedFiles), hiddenCounts: { ...seedHiddenFileCounts } };
    emit();
  },
};

export function fileTypeFromName(name: string): FileType {
  const ext = name.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'pdf':
      return 'PDF';
    case 'doc':
    case 'docx':
      return 'DOCX';
    case 'md':
    case 'markdown':
      return 'MD';
    case 'xls':
    case 'xlsx':
    case 'csv':
      return 'XLSX';
    case 'zip':
      return 'ZIP';
    default:
      return 'TXT';
  }
}

export function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export const delay = (ms = 240) => new Promise((r) => setTimeout(r, ms));
