import { MoreHorizontal, Pin, PinOff, SquarePen, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { NavLink, useMatch, useNavigate } from 'react-router-dom';

import { Menu } from '@/components/ui/Menu';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { DeleteConversationDialog } from '@/pages/chat/components/DeleteConversationDialog';
import { useRenameTarget } from '@/pages/chat/rename';
import { isBusy, lastAssistant, renameConversation, sidebarConversations, TITLE_MAX, togglePin, useChat, type Conversation } from '@/services/chat';

/**
 * 侧栏对话列表（F5）：全部对话直接在侧栏列出并可滚动，置顶分组在前；
 * 悬停行显示「···」，菜单可重命名（行内编辑）、置顶、删除（二次确认）。
 */
export function ConversationList() {
  const { pinned, recent } = useChat((s) => sidebarConversations(s));
  const [renaming, setRenaming] = useRenameTarget();
  const [deleting, setDeleting] = useState<Conversation | null>(null);
  const navigate = useNavigate();
  const current = useMatch('/chat/:conversationId')?.params.conversationId;

  const row = (c: Conversation) => (
    <Row key={c.id} c={c} active={c.id === current} renaming={renaming === c.id} onRename={() => setRenaming(c.id)} onRenameEnd={() => setRenaming(undefined)} onDelete={() => setDeleting(c)} />
  );

  return (
    <nav aria-label="对话" className="-mr-2 flex min-h-0 flex-1 flex-col overflow-y-auto pr-2 [scrollbar-width:thin]">
      {pinned.length > 0 && (
        <>
          <p className="px-3 pt-2 pb-1 text-[10px] text-faint">置顶</p>
          <ul className="flex flex-col">{pinned.map(row)}</ul>
          <p className="px-3 pt-2 pb-1 text-[10px] text-faint">最近</p>
        </>
      )}
      <ul className="flex flex-col">{recent.map(row)}</ul>
      {!pinned.length && !recent.length && <p className="px-3 py-2 text-[11.5px] text-faint">还没有对话</p>}
      <DeleteConversationDialog
        conversation={deleting}
        onClose={() => setDeleting(null)}
        onDeleted={(c) => {
          if (c.id === current) navigate('/chat', { replace: true });
        }}
      />
    </nav>
  );
}

interface RowProps {
  c: Conversation;
  active: boolean;
  renaming: boolean;
  onRename: () => void;
  onRenameEnd: () => void;
  onDelete: () => void;
}

function Row({ c, active, renaming, onRename, onRenameEnd, onDelete }: RowProps) {
  const busy = isBusy(lastAssistant(c));
  if (renaming) return <RenameInput c={c} onDone={onRenameEnd} />;
  return (
    <li className="group relative">
      <NavLink
        to={`/chat/${c.id}`}
        onKeyDown={(e) => {
          if (e.key === 'F2') {
            e.preventDefault();
            onRename();
          }
        }}
        className={cn(
          'flex h-7 w-full items-center gap-1.5 rounded-[7px] pr-8 pl-3 text-[12px] text-text2 transition-colors hover:bg-active/60',
          active && 'bg-active font-medium text-ink',
        )}
      >
        {c.pinned && <Pin aria-label="已置顶" className="size-3 shrink-0 text-muted" />}
        <span className="truncate">{c.title}</span>
        {busy && <span aria-label="生成中" className="ml-auto size-1.5 shrink-0 animate-pulse rounded-full bg-ink" />}
      </NavLink>
      <div className="absolute top-1/2 right-1 -translate-y-1/2">
        <Menu
          side
          width={160}
          items={[
            { key: 'rename', label: '重命名', icon: <SquarePen />, hint: 'F2', onSelect: onRename },
            { key: 'pin', label: c.pinned ? '取消置顶' : '置顶', icon: c.pinned ? <PinOff /> : <Pin />, onSelect: () => togglePin(c.id) },
            { key: 'delete', label: '删除对话', icon: <Trash2 />, danger: true, divider: true, onSelect: onDelete },
          ]}
          trigger={({ open, toggle }) => (
            <button
              type="button"
              aria-label={`${c.title} 的更多操作`}
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={toggle}
              className={cn(
                'flex size-[22px] items-center justify-center rounded-[5px] text-muted transition-opacity hover:bg-[#dadad5] hover:text-ink focus-visible:opacity-100',
                open ? 'bg-[#dadad5] text-ink opacity-100' : 'opacity-0 group-hover:opacity-100',
              )}
            >
              <MoreHorizontal className="size-3.5" />
            </button>
          )}
        />
      </div>
    </li>
  );
}

/** 行内重命名：Enter 保存 · Esc 取消 · 失焦保存 */
function RenameInput({ c, onDone }: { c: Conversation; onDone: () => void }) {
  const toast = useToast();
  const [value, setValue] = useState(c.title);
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);

  const save = async () => {
    if (done.current) return;
    done.current = true;
    const t = value.trim();
    if (t && t !== c.title) {
      await renameConversation(c.id, t);
      toast('已重命名', { tone: 'success' });
    }
    onDone();
  };
  const cancel = () => {
    done.current = true;
    onDone();
  };

  return (
    <li>
      <input
        ref={ref}
        value={value}
        maxLength={TITLE_MAX}
        aria-label="对话标题"
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) void save();
          if (e.key === 'Escape') {
            e.stopPropagation();
            cancel();
          }
        }}
        className="h-7 w-full rounded-[7px] border border-ink bg-white px-[11px] text-[12px] text-ink"
      />
    </li>
  );
}
