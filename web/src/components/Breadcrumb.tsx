import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

/** 面包屑：返回箭头 + 层级，11px */
export function Breadcrumb({ items }: { items: { label: string; to?: string }[] }) {
  const back = [...items].reverse().find((i) => i.to);
  return (
    <nav aria-label="面包屑" className="flex items-center gap-1.5">
      {back?.to && (
        <Link to={back.to} aria-label="返回" className="text-muted hover:text-ink">
          <ArrowLeft className="size-[11px]" />
        </Link>
      )}
      {items.map((it, i) => (
        <span key={it.label} className="flex items-center gap-1.5">
          {i > 0 && <span className="text-faint">/</span>}
          {it.to ? (
            <Link to={it.to} className="text-muted hover:text-ink">
              {it.label}
            </Link>
          ) : (
            <span className="text-text2">{it.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
