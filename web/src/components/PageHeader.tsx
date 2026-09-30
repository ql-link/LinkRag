import type { ReactNode } from 'react';

interface PageHeaderProps {
  eyebrow: ReactNode;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}

/** 页头：小字眉标 + 衬线标题 + 描述，下方 24px 后接分隔线 */
export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <>
      <header className="flex items-start gap-4">
        <div className="flex min-w-0 flex-col">
          <div className="text-[11px] leading-none text-muted">{eyebrow}</div>
          <h1 className="mt-2 font-serif text-[28px] leading-[1.35] font-semibold text-ink">{title}</h1>
          {description && <p className="mt-1.5 text-[13px] leading-none text-text2">{description}</p>}
        </div>
        {actions && <div className="ml-auto flex shrink-0 items-center gap-3.5">{actions}</div>}
      </header>
      <div className="mt-6 mb-7 h-px bg-divider" />
    </>
  );
}
