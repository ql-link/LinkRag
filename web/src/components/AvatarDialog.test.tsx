import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';

import { AvatarDialog } from './AvatarDialog';
import { UserAvatar } from './UserAvatar';

import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { ToastProvider } from '@/contexts/ToastContext';
import { exportAvatar, loadAvatar } from '@/lib/avatarCrop';

vi.mock('@/lib/avatarCrop', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/avatarCrop')>(),
  loadAvatar: vi.fn(),
  exportAvatar: vi.fn(),
}));

const user = { username: 'chenmo', displayName: '陈默', email: 'chenmo@example.com', avatarUrl: 'old-avatar.png' };
function Harness() {
  const [open, setOpen] = useState(true);
  const { user: current } = useAuth();
  return <><button onClick={() => setOpen(true)}>修改头像</button>{current && <UserAvatar user={current} />}<AvatarDialog open={open} onClose={() => setOpen(false)} /></>;
}
function setup() {
  localStorage.setItem('linkrag.user', JSON.stringify(user));
  vi.mocked(loadAvatar).mockResolvedValue({ image: new Image(), url: 'blob:new', name: 'photo.png', width: 800, height: 400 });
  vi.mocked(exportAvatar).mockResolvedValue(new File(['png'], 'avatar.png', { type: 'image/png' }));
  vi.stubGlobal('URL', { revokeObjectURL: vi.fn() });
  return render(<ToastProvider><AuthProvider><Harness /></AuthProvider></ToastProvider>);
}
function choose() {
  fireEvent.change(screen.getByLabelText('选择头像图片'), { target: { files: [new File(['png'], 'photo.png', { type: 'image/png' })] } });
}
afterEach(() => { localStorage.clear(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

describe('avatar editor', () => {
  it('starts with upload disabled and cancelling a crop preserves the current avatar', async () => {
    setup();
    expect(screen.getByRole('button', { name: '保存头像' })).toBeDisabled();
    choose();
    await screen.findByRole('dialog', { name: '调整头像' });
    fireEvent.change(screen.getByRole('slider', { name: '头像缩放' }), { target: { value: '2' } });
    expect(screen.getByText('200%')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('linkrag.user')!).avatarUrl).toBe('old-avatar.png');
    expect(exportAvatar).not.toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:new');
    fireEvent.click(screen.getByRole('button', { name: '修改头像' }));
    expect(screen.getByRole('dialog', { name: '修改头像' })).toBeInTheDocument();
  });

  it('saves the crop and updates shared avatar state and persistent profile', async () => {
    setup(); choose();
    await screen.findByRole('dialog', { name: '调整头像' });
    fireEvent.click(screen.getByRole('button', { name: '保存头像' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('头像已更新')).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('linkrag.user')!).avatarUrl).toMatch(/^data:image\/png;base64,/);
    expect(screen.getByRole('img', { name: '陈默的头像' }).getAttribute('src')).toMatch(/^data:image\/png;base64,/);
  });

  it('keeps the crop after an error and supports retrying', async () => {
    setup(); choose();
    await screen.findByRole('dialog', { name: '调整头像' });
    vi.mocked(exportAvatar).mockRejectedValueOnce(new Error('图片处理失败'));
    fireEvent.click(screen.getByRole('button', { name: '保存头像' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('图片处理失败');
    expect(JSON.parse(localStorage.getItem('linkrag.user')!).avatarUrl).toBe('old-avatar.png');
    fireEvent.click(screen.getByRole('button', { name: '保存头像' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('shows decoding errors without entering crop mode', async () => {
    setup();
    vi.mocked(loadAvatar).mockRejectedValueOnce(new Error('无法读取这张图片'));
    choose();
    expect(await screen.findByRole('alert')).toHaveTextContent('无法读取这张图片');
    expect(screen.getByRole('dialog', { name: '修改头像' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存头像' })).toBeDisabled();
  });

  it('falls back to an initial for a broken image', () => {
    render(<UserAvatar user={user} />);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('陈')).toBeInTheDocument();
  });
});
