import { useSyncExternalStore } from 'react';

/**
 * 侧栏当前处于行内重命名的对话（F5）。
 * 纯界面状态，不经过服务层。
 */
let target: string | undefined;
const listeners = new Set<() => void>();
const set = (id: string | undefined) => {
  target = id;
  listeners.forEach((l) => l());
};
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export function useRenameTarget(): [string | undefined, (id: string | undefined) => void] {
  return [useSyncExternalStore(subscribe, () => target), set];
}

