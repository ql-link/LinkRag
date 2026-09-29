import { Search } from 'lucide-react';

import { cn } from '@/lib/cn';

interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
}

export function SearchBox({ value, onChange, placeholder, className }: SearchBoxProps) {
  return (
    <label
      className={cn(
        'flex items-center gap-[7px] rounded-[7px] border border-line bg-white px-2.5 py-[7px] focus-within:border-ink',
        className,
      )}
    >
      <Search aria-hidden className="size-3 shrink-0 text-muted" strokeWidth={2} />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="w-full min-w-0 bg-transparent text-[12px] leading-none text-ink outline-none placeholder:text-muted"
      />
    </label>
  );
}
