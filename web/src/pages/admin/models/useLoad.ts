import { useCallback, useEffect, useRef, useState } from 'react';

import { errMsg } from './helpers';

/** 加载 + 刷新：刷新失败时保留上一次数据，由调用方展示 StaleBanner */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  const reload = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    run()
      .then((d) => {
        if (id !== seq.current) return;
        setData(d);
        setError(null);
      })
      .catch((e) => id === seq.current && setError(errMsg(e, '加载失败')))
      .finally(() => id === seq.current && setLoading(false));
  }, [run]);
  useEffect(reload, [reload]);

  return { data, error, loading, reload, setData };
}
