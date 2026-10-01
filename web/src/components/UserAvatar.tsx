import { useState } from 'react';

import { cn } from '@/lib/cn';
import type { User } from '@/types';

export function UserAvatar({ user, className }: { user: Pick<User, 'displayName' | 'username' | 'avatarUrl'>; className?: string }) {
  const [failedUrl, setFailedUrl] = useState<string>();
  return (
    <span className={cn('relative flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-full bg-ink text-xl font-medium text-white', className)}>
      {user.avatarUrl && user.avatarUrl !== failedUrl ? (
        <img src={user.avatarUrl} alt={`${user.displayName || user.username}的头像`} className="size-full object-cover" onError={() => setFailedUrl(user.avatarUrl)} />
      ) : (
        <span aria-hidden>{Array.from(user.displayName.trim() || user.username)[0]?.toUpperCase()}</span>
      )}
    </span>
  );
}
