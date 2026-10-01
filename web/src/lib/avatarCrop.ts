export interface CropImage {
  image: HTMLImageElement;
  url: string;
  name: string;
  width: number;
  height: number;
}

export interface CropPosition {
  x: number;
  y: number;
  zoom: number;
}

export function validateAvatar(file: File) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('请选择 JPG、PNG 或 WebP 图片。');
  if (file.size > 5 * 1024 * 1024) throw new Error('图片不能超过 5 MB。');
}

export async function loadAvatar(file: File): Promise<CropImage> {
  validateAvatar(file);
  const url = URL.createObjectURL(file);
  const image = new Image();
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error('无法读取这张图片，请选择其他图片。'));
      image.src = url;
    });
    return { image, url, name: file.name, width: image.naturalWidth, height: image.naturalHeight };
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  }
}

export function cropSize(image: Pick<CropImage, 'width' | 'height'>, zoom: number) {
  return Math.min(image.width, image.height) * 0.9 / zoom;
}

export function clampCrop(image: Pick<CropImage, 'width' | 'height'>, position: CropPosition): CropPosition {
  const zoom = Math.max(1, Math.min(3, position.zoom));
  const half = cropSize(image, zoom) / 2;
  return { x: Math.max(half, Math.min(image.width - half, position.x)), y: Math.max(half, Math.min(image.height - half, position.y)), zoom };
}

export function cropImageStyle(image: Pick<CropImage, 'width' | 'height'>, position: CropPosition, viewport: number, guideRatio = 1) {
  const scale = viewport * guideRatio / cropSize(image, position.zoom);
  return { width: image.width * scale, height: image.height * scale, left: viewport / 2 - position.x * scale, top: viewport / 2 - position.y * scale };
}

export async function exportAvatar(image: CropImage, position: CropPosition): Promise<File> {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 512;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('当前浏览器无法处理图片，请更换浏览器后重试。');
  const crop = clampCrop(image, position);
  const size = cropSize(image, crop.zoom);
  context.drawImage(image.image, crop.x - size / 2, crop.y - size / 2, size, size, 0, 0, 512, 512);
  const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((result) => result ? resolve(result) : reject(new Error('图片处理失败，请重新选择图片。')), 'image/png'));
  return new File([blob], 'avatar.png', { type: 'image/png' });
}
