import { useSyncExternalStore } from 'react';

import { db } from '@/mock/db';

import { backendReady, onBackendReady } from './backend';

/** 订阅 Mock 数据变化；selector 每次渲染重新计算，数据量小无需 memo */
export function useStore<T>(selector: (state: typeof db.state) => T): T {
  useSyncExternalStore(db.subscribe, db.getVersion);
  return selector(db.state);
}

/** 真实模式下登录后数据是否已装载完成；Mock 模式恒为 true。直达详情路由时用于区分「加载中」与「不存在」 */
export function useBackendReady(): boolean {
  return useSyncExternalStore(onBackendReady, backendReady);
}
