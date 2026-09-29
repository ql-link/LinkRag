/**
 * 全局请求计数：request() 进出时增减，AppLayout 顶部进度条据此显示「加载中」。
 * SSE 问答流不计入（其进度由对话页自身的思考过程展示）。
 */
let count = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export const pending = {
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
  get: () => count,
  start() {
    count += 1;
    emit();
  },
  end() {
    count = Math.max(0, count - 1);
    emit();
  },
};

/** 包裹一个异步任务：执行期间计入全局加载状态 */
export async function track<T>(p: Promise<T>): Promise<T> {
  pending.start();
  try {
    return await p;
  } finally {
    pending.end();
  }
}
