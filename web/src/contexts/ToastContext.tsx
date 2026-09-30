import { AlertCircle, CheckCircle2 } from 'lucide-react';
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

interface ToastState {
  id: number;
  message: string;
  tone: 'info' | 'error' | 'success';
  action?: { label: string; onClick: () => void };
  icon?: ReactNode;
}

type ShowToast = (message: string, opts?: Partial<Omit<ToastState, 'id' | 'message'>>) => void;

const ToastContext = createContext<ShowToast>(() => {});

/** 浅色提示卡：白底描边 + 柔和阴影、圆角 10、底部居中；状态以图标颜色区分 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const show = useCallback<ShowToast>((message, opts) => {
    clearTimeout(timer.current);
    setToast({ id: Date.now(), message, tone: opts?.tone ?? 'info', action: opts?.action, icon: opts?.icon });
    timer.current = setTimeout(() => setToast(null), 3200);
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-9 z-[60] flex justify-center">
        {toast && (
          <div key={toast.id} className="pointer-events-auto flex animate-rise-in items-center gap-2 rounded-[10px] border border-line bg-white py-2.5 pr-4 pl-3.5 text-[12.5px] text-ink shadow-[0_2px_6px_0_rgba(28,26,20,0.05),0_12px_28px_-6px_rgba(28,26,20,0.14)]">
            {toast.icon ??
              (toast.tone === 'error' ? (
                <AlertCircle aria-hidden className="size-3.5 text-red" />
              ) : toast.tone === 'success' ? (
                <CheckCircle2 aria-hidden className="size-3.5 text-green" />
              ) : null)}
            <span>{toast.message}</span>
            {toast.action && (
              <button
                type="button"
                className="ml-1 font-medium text-[#a8733f] underline-offset-2 hover:underline"
                onClick={() => {
                  toast.action?.onClick();
                  setToast(null);
                }}
              >
                {toast.action.label}
              </button>
            )}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => useContext(ToastContext);
