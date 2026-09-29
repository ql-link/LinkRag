import { useEffect, useState } from 'react';

/**
 * 页面级数据装载：页面所需的全部请求（传入的 loader 内部自行 Promise.all）结束后才返回 true，
 * 页面据此一次性展示，而不是各接口返回后分块陆续出现。失败同样视为结束，由 onError 提示。
 */
export function usePageLoad(loader: () => Promise<unknown>, deps: unknown[], onError?: (e: unknown) => void): boolean {
  const [done, setDone] = useState(false);
  useEffect(() => {
    let alive = true;
    setDone(false);
    loader()
      .catch((e: unknown) => alive && onError?.(e))
      .finally(() => alive && setDone(true));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return done;
}
