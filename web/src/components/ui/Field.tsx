import { AlertCircle } from 'lucide-react';
import { useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from 'react';

import { cn } from '@/lib/cn';

interface FieldProps {
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: (id: string, describedBy?: string) => ReactNode;
}

/** 表单字段：标签 + 控件 + 提示/错误 */
export function Field({ label, required, hint, error, children }: FieldProps) {
  const id = useId();
  const noteId = hint || error ? `${id}-note` : undefined;
  return (
    <div className="flex w-full flex-col gap-[7px]">
      <label htmlFor={id} className="flex gap-1 text-[12px] leading-none font-medium text-ink">
        {label}
        {required && <span className="font-normal text-red">*</span>}
      </label>
      {children(id, noteId)}
      {error ? (
        <p id={noteId} role="alert" className="flex items-center gap-[5px] text-[11.5px] leading-none text-red">
          <AlertCircle aria-hidden className="size-3" />
          {error}
        </p>
      ) : hint ? (
        <p id={noteId} className="text-[11.5px] leading-none text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode;
  trailing?: ReactNode;
  invalid?: boolean;
  height?: 40 | 42;
}

export function TextInput({ icon, trailing, invalid, height = 40, className, ...rest }: TextInputProps) {
  return (
    <div
      className={cn(
        'flex w-full items-center gap-[9px] rounded-[9px] border bg-white px-3 transition-shadow',
        height === 42 ? 'h-[42px]' : 'h-10',
        invalid ? 'border-red' : 'border-line focus-within:border-ink focus-within:shadow-ring',
        className,
      )}
    >
      {icon && <span className="flex size-3.5 shrink-0 items-center text-muted [&>svg]:size-3.5">{icon}</span>}
      <input
        aria-invalid={invalid || undefined}
        className="h-full w-full min-w-0 bg-transparent text-[13px] text-ink outline-none placeholder:text-faint"
        {...rest}
      />
      {trailing}
    </div>
  );
}

export function TextArea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'h-[84px] w-full resize-none rounded-[9px] border border-line bg-white px-3 pt-[11px] text-[13px] text-ink outline-none placeholder:text-faint focus:border-ink focus:shadow-ring',
        className,
      )}
      {...rest}
    />
  );
}
