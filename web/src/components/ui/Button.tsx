import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  icon?: ReactNode;
  /** 图标放在文字之后（如登录按钮的箭头） */
  trailingIcon?: ReactNode;
  block?: boolean;
  size?: 'md' | 'lg';
}

const variants: Record<Variant, string> = {
  primary: 'bg-ink text-white font-medium hover:bg-[#33332f]',
  secondary: 'bg-white border border-line text-text2 hover:bg-soft',
  danger: 'bg-red text-white font-medium hover:bg-[#b93e35]',
  ghost: 'text-text2 hover:bg-soft',
};

export function Button({
  variant = 'primary',
  icon,
  trailingIcon,
  block,
  size = 'md',
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-[7px] text-[12px] leading-[17px] whitespace-nowrap transition-colors disabled:opacity-60',
        variant === 'secondary' ? 'py-2 pr-3.5 pl-[13px]' : 'py-[9px] pr-4 pl-[13px]',
        !icon && 'px-[17px]',
        size === 'lg' && 'py-3',
        block && 'w-full',
        variants[variant],
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
      {trailingIcon}
    </button>
  );
}
