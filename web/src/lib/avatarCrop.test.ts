import { clampCrop, cropImageStyle, cropSize, exportAvatar, loadAvatar, validateAvatar, type CropImage } from './avatarCrop';

afterEach(() => vi.restoreAllMocks());

describe('avatar crop', () => {
  it('accepts supported images and rejects unsupported or oversized uploads', () => {
    expect(() => validateAvatar(new File(['image'], 'a.png', { type: 'image/png' }))).not.toThrow();
    expect(() => validateAvatar(new File(['image'], 'a.svg', { type: 'image/svg+xml' }))).toThrow('JPG、PNG 或 WebP');
    expect(() => validateAvatar(new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'a.png', { type: 'image/png' }))).toThrow('5 MB');
  });

  it('clamps the crop to the image edges at every zoom', () => {
    const image = { width: 800, height: 400 };
    expect(cropSize(image, 1)).toBe(360);
    expect(clampCrop(image, { x: -100, y: 1000, zoom: 1 })).toEqual({ x: 180, y: 220, zoom: 1 });
    expect(clampCrop(image, { x: 0, y: 0, zoom: 3 })).toEqual({ x: 60, y: 60, zoom: 3 });
    expect(clampCrop(image, { x: 400, y: 200, zoom: 8 }).zoom).toBe(3);
  });

  it('shows exactly the same crop in the guide and the circular preview', () => {
    const image = { width: 640, height: 480 };
    const position = { x: 350, y: 220, zoom: 1.5 };
    const size = cropSize(image, position.zoom);
    const editor = cropImageStyle(image, position, 320, 0.9);
    const preview = cropImageStyle(image, position, 112);
    expect((16 - editor.left) / (editor.width / image.width)).toBeCloseTo(position.x - size / 2);
    expect(-preview.left / (preview.width / image.width)).toBeCloseTo(position.x - size / 2);
    expect(-preview.top / (preview.height / image.height)).toBeCloseTo(position.y - size / 2);
  });

  it('exports the chosen source rectangle as a 512px PNG', async () => {
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback) => callback(new Blob(['png'], { type: 'image/png' })));
    const image = { image: new Image(), width: 800, height: 400, url: 'blob:avatar', name: 'photo.png' };
    const result = await exportAvatar(image, { x: 400, y: 200, zoom: 1 });
    expect(drawImage).toHaveBeenCalledWith(image.image, 220, 20, 360, 360, 0, 0, 512, 512);
    expect(result).toBeInstanceOf(File);
    expect(result.type).toBe('image/png');
  });

  it('releases the object URL when image decoding fails', async () => {
    const revoke = vi.fn();
    vi.stubGlobal('URL', { createObjectURL: () => 'blob:broken', revokeObjectURL: revoke });
    vi.stubGlobal('Image', class { onerror?: () => void; set src(_: string) { this.onerror?.(); } });
    await expect(loadAvatar(new File(['broken'], 'photo.png', { type: 'image/png' }))).rejects.toThrow('无法读取');
    expect(revoke).toHaveBeenCalledWith('blob:broken');
    vi.unstubAllGlobals();
  });

  it('reports canvas encoding failure without uploading an empty image', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback) => callback(null));
    await expect(exportAvatar({ image: new Image(), width: 100, height: 100 } as CropImage, { x: 50, y: 50, zoom: 1 })).rejects.toThrow('图片处理失败');
  });
});
