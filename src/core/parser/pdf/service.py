from __future__ import annotations

import mimetypes
import re
from dataclasses import asdict
from pathlib import Path

import cv2
import fitz
import numpy as np

from src.core.parser.pdf.backends.mineru_backend import MinerUBackend
from src.core.parser.pdf.backends.naive_backend import NaivePdfBackend
from src.core.parser.pdf.models import PdfBinaryAsset, PdfImageAsset, PdfParseOptions


class PdfParserService:
    PLACEHOLDER_PATTERNS = {
        "naive": re.compile(
            r"\*\*==> picture "
            r"(?:page (?P<page>\d+) image (?P<image>\d+)|\[(?P<width>\d+) x (?P<height>\d+)\]) "
            r"intentionally omitted <==\*\*"
        ),
        "docling": re.compile(r"<!-- image -->"),
    }
    MIN_IMAGE_BYTES = 2048
    MIN_IMAGE_WIDTH = 64
    MIN_IMAGE_HEIGHT = 64

    def __init__(self) -> None:
        self._backends = {
            NaivePdfBackend.name: NaivePdfBackend,
            # MinerU 需要 API URL，在 _create_backend_instance 中动态实例化
        }

    def parse(self, file_stream: bytes, options: PdfParseOptions) -> tuple[str, dict]:
        metadata: dict = {
            "pdf_parser_requested_backend": options.backend,
            "pdf_parser_attempts": [],
        }

        backend_order = self._build_backend_order(options.backend)
        markdown = ""
        binary_assets: list[PdfBinaryAsset] = []
        selected_backend = None
        backend_instance = None

        for backend_name in backend_order:
            backend_instance = self._create_backend_instance(backend_name, options)
            if backend_instance is None:
                metadata["pdf_parser_attempts"].append(
                    {
                        "backend": backend_name,
                        "success": False,
                        "reason": "unsupported backend",
                    }
                )
                continue

            markdown, binary_assets = backend_instance.parse(file_stream, options)
            metadata.update(backend_instance.metadata)
            if markdown and markdown.strip():
                selected_backend = backend_name
                metadata["pdf_parser_attempts"].append({"backend": backend_name, "success": True})
                break
            metadata["pdf_parser_attempts"].append(
                {
                    "backend": backend_name,
                    "success": False,
                    "reason": backend_instance.metadata.get(
                        f"{backend_name}_backend_error", "empty result"
                    ),
                }
            )

        if not markdown:
            markdown, binary_assets = NaivePdfBackend().parse(file_stream, options)
            selected_backend = "naive"
            metadata["pdf_parser_attempts"].append({"backend": "naive", "success": True})

        metadata["pdf_parser_backend"] = selected_backend or "naive"

        if options.storage and options.image_bucket and options.image_prefix:
            placeholder_count = self._count_placeholders(markdown, metadata["pdf_parser_backend"])
            image_assets = self._upload_images(
                file_stream,
                options,
                backend=metadata["pdf_parser_backend"],
                placeholder_count=placeholder_count,
                binary_assets=binary_assets,
            )
            markdown = self._inject_image_references(
                markdown, metadata["pdf_parser_backend"], image_assets
            )
            metadata["image_assets"] = [asdict(asset) for asset in image_assets]
        else:
            metadata["image_assets"] = []

        return markdown, metadata

    def _create_backend_instance(self, backend_name: str, options: PdfParseOptions):
        """根据后端名称创建实例。MinerU 需要特殊处理（传入 API URL）。"""
        if backend_name == MinerUBackend.name:
            api_url = getattr(options, "mineru_api_url", None) or ""
            api_key = getattr(options, "mineru_api_key", None)
            timeout = getattr(options, "mineru_timeout", 300)
            if not api_url:
                return None
            return MinerUBackend(api_url=api_url, api_key=api_key, timeout=timeout)

        backend_cls = self._backends.get(backend_name)
        if backend_cls is None:
            return None
        return backend_cls()

    def _build_backend_order(self, backend: str) -> list[str]:
        normalized = (backend or "naive").lower()
        if normalized == "auto":
            return ["mineru", "naive"]
        if normalized == "mineru":
            return ["mineru", "naive"]
        return ["naive"]

    def _count_placeholders(self, markdown: str, backend: str) -> int:
        pattern = self.PLACEHOLDER_PATTERNS.get(backend)
        if not pattern or not markdown:
            return 0
        return sum(1 for _ in pattern.finditer(markdown))

    def _upload_images(
        self,
        file_stream: bytes,
        options: PdfParseOptions,
        *,
        backend: str,
        placeholder_count: int,
        binary_assets: list[PdfBinaryAsset],
    ) -> list[PdfImageAsset]:
        image_assets: list[PdfImageAsset] = []

        # 优先使用 Docling 已提取的图片/表格/页图资产
        if binary_assets:
            for asset in binary_assets:
                object_key = self._build_image_object_key(
                    options.image_prefix,
                    f"{asset.kind}-page-{asset.page_number:03d}-{asset.index:02d}.{asset.ext}",
                )
                content_type = mimetypes.types_map.get(f".{asset.ext}", "image/png")
                options.storage.upload_bytes(
                    bucket=options.image_bucket,
                    object_key=object_key,
                    content=asset.content,
                    content_type=content_type,
                )
                url = options.storage.build_object_url(options.image_bucket, object_key)
                image_size = self._get_image_size(asset.content)
                image_assets.append(
                    PdfImageAsset(
                        page_number=asset.page_number,
                        index=asset.index,
                        object_key=object_key,
                        url=url,
                        width=image_size[0],
                        height=image_size[1],
                    )
                )
            return image_assets

        doc = fitz.open(stream=file_stream, filetype="pdf")

        # Docling 没有资产时，回退 PyMuPDF 抽内嵌图
        for page_index, page in enumerate(doc, start=1):
            images = page.get_images(full=True)
            for image_index, image in enumerate(images, start=1):
                xref = image[0]
                extracted = doc.extract_image(xref)
                if not extracted:
                    continue
                ext = (extracted.get("ext") or "png").lower()
                image_bytes = extracted["image"]
                if not self._is_meaningful_image(image_bytes):
                    continue
                object_key = self._build_image_object_key(
                    options.image_prefix,
                    f"page-{page_index:03d}-image-{image_index:02d}.{ext}",
                )
                content_type = mimetypes.types_map.get(f".{ext}", "image/png")
                options.storage.upload_bytes(
                    bucket=options.image_bucket,
                    object_key=object_key,
                    content=image_bytes,
                    content_type=content_type,
                )
                url = options.storage.build_object_url(options.image_bucket, object_key)
                image_assets.append(
                    PdfImageAsset(
                        page_number=page_index,
                        index=image_index,
                        object_key=object_key,
                        url=url,
                        width=self._get_image_size(image_bytes)[0],
                        height=self._get_image_size(image_bytes)[1],
                    )
                )

        if not image_assets and backend == "naive":
            for page_index, page in enumerate(doc, start=1):
                image_blocks = [
                    block
                    for block in page.get_text("dict").get("blocks", [])
                    if block.get("type") == 1
                ]
                image_blocks.sort(
                    key=lambda block: (
                        round(block["bbox"][1], 1),
                        round(block["bbox"][0], 1),
                        round(block["bbox"][2], 1),
                    )
                )
                for image_index, block in enumerate(image_blocks, start=1):
                    image_bytes = block.get("image")
                    if not image_bytes:
                        continue
                    if not self._is_meaningful_image(image_bytes):
                        continue
                    ext = (block.get("ext") or "png").lower()
                    object_key = self._build_image_object_key(
                        options.image_prefix,
                        f"page-{page_index:03d}-block-{image_index:02d}.{ext}",
                    )
                    content_type = mimetypes.types_map.get(f".{ext}", "image/png")
                    options.storage.upload_bytes(
                        bucket=options.image_bucket,
                        object_key=object_key,
                        content=image_bytes,
                        content_type=content_type,
                    )
                    url = options.storage.build_object_url(options.image_bucket, object_key)
                    image_assets.append(
                        PdfImageAsset(
                            page_number=page_index,
                            index=image_index,
                            object_key=object_key,
                            url=url,
                            width=self._get_image_size(image_bytes)[0],
                            height=self._get_image_size(image_bytes)[1],
                        )
                    )

            if not image_assets:
                image_assets = self._upload_rendered_visual_regions(doc, options)

            return image_assets

        # 如果 PDF 没有内嵌图片（常见于纯矢量页/扫描页），但 Markdown 有图片占位符，
        # 则按页渲染为图片上传，确保 Markdown 可引用可视内容。
        if not image_assets and placeholder_count > 0:
            for page_index, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_bytes = pix.tobytes("png")
                object_key = self._build_image_object_key(
                    options.image_prefix,
                    f"page-{page_index:03d}-render.png",
                )
                options.storage.upload_bytes(
                    bucket=options.image_bucket,
                    object_key=object_key,
                    content=image_bytes,
                    content_type="image/png",
                )
                url = options.storage.build_object_url(options.image_bucket, object_key)
                image_assets.append(
                    PdfImageAsset(
                        page_number=page_index,
                        index=1,
                        object_key=object_key,
                        url=url,
                        width=pix.width,
                        height=pix.height,
                    )
                )

        return image_assets

    def _upload_rendered_visual_regions(
        self, doc: fitz.Document, options: PdfParseOptions
    ) -> list[PdfImageAsset]:
        image_assets: list[PdfImageAsset] = []
        for page_index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            page_image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height,
                pix.width,
                pix.n,
            )
            if pix.n == 4:
                page_image = cv2.cvtColor(page_image, cv2.COLOR_RGBA2RGB)
            text_bboxes = self._get_rendered_text_bboxes(page, pix.width, pix.height)
            table_bboxes = self._get_rendered_table_bboxes(page, pix.width, pix.height)
            regions = self._detect_visual_regions(
                page_image,
                text_bboxes=text_bboxes,
                excluded_bboxes=table_bboxes,
            )
            for region_index, (x, y, w, h) in enumerate(regions, start=1):
                crop = page_image[y : y + h, x : x + w]
                success, encoded = cv2.imencode(".png", cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
                if not success:
                    continue
                image_bytes = encoded.tobytes()
                if not self._is_meaningful_image(image_bytes):
                    continue
                object_key = self._build_image_object_key(
                    options.image_prefix,
                    f"page-{page_index:03d}-region-{region_index:02d}.png",
                )
                options.storage.upload_bytes(
                    bucket=options.image_bucket,
                    object_key=object_key,
                    content=image_bytes,
                    content_type="image/png",
                )
                url = options.storage.build_object_url(options.image_bucket, object_key)
                image_assets.append(
                    PdfImageAsset(
                        page_number=page_index,
                        index=region_index,
                        object_key=object_key,
                        url=url,
                        width=w,
                        height=h,
                    )
                )
        return image_assets

    def _detect_visual_regions(
        self,
        page_image: np.ndarray,
        *,
        text_bboxes: list[tuple[int, int, int, int]] | None = None,
        excluded_bboxes: list[tuple[int, int, int, int]] | None = None,
    ) -> list[tuple[int, int, int, int]]:
        height, width = page_image.shape[:2]
        gray = cv2.cvtColor(page_image, cv2.COLOR_RGB2GRAY)
        _, dark_mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)
        for x, y, w, h in text_bboxes or []:
            pad = 3
            x0 = max(0, x - pad)
            y0 = max(0, y - pad)
            x1 = min(width, x + w + pad)
            y1 = min(height, y + h + pad)
            dark_mask[y0:y1, x0:x1] = 0

        close_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(25, width // 35), max(18, height // 70)),
        )
        merged = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, close_kernel, iterations=2)
        merged = cv2.dilate(
            merged,
            cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)),
            iterations=1,
        )

        contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_w = max(160, int(width * 0.18))
        min_h = max(120, int(height * 0.08))
        min_area = width * height * 0.015
        regions: list[tuple[int, int, int, int]] = []

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < min_w or h < min_h or w * h < min_area:
                continue
            if w > width * 0.96 and h > height * 0.9:
                continue
            if self._is_excluded_region((x, y, w, h), excluded_bboxes or []):
                continue

            content = dark_mask[y : y + h, x : x + w]
            density = cv2.countNonZero(content) / float(w * h)
            if density < 0.015 or density > 0.75:
                continue

            pad = 16
            x0 = max(0, x - pad)
            y0 = max(0, y - pad)
            x1 = min(width, x + w + pad)
            y1 = min(height, y + h + pad)
            regions.append((x0, y0, x1 - x0, y1 - y0))

        return self._merge_regions(regions)

    @staticmethod
    def _is_excluded_region(
        region: tuple[int, int, int, int],
        excluded_bboxes: list[tuple[int, int, int, int]],
    ) -> bool:
        rx, ry, rw, rh = region
        region_area = float(rw * rh)
        if region_area <= 0:
            return False
        for ex, ey, ew, eh in excluded_bboxes:
            ix0 = max(rx, ex)
            iy0 = max(ry, ey)
            ix1 = min(rx + rw, ex + ew)
            iy1 = min(ry + rh, ey + eh)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            overlap_area = float((ix1 - ix0) * (iy1 - iy0))
            excluded_area = float(ew * eh)
            if overlap_area / region_area >= 0.35 or overlap_area / excluded_area >= 0.55:
                return True
        return False

    @staticmethod
    def _get_rendered_text_bboxes(
        page: fitz.Page,
        rendered_width: int,
        rendered_height: int,
    ) -> list[tuple[int, int, int, int]]:
        return PdfParserService._scale_page_bboxes(
            page,
            [
                block["bbox"]
                for block in page.get_text("dict").get("blocks", [])
                if block.get("type") == 0
            ],
            rendered_width,
            rendered_height,
        )

    @staticmethod
    def _get_rendered_table_bboxes(
        page: fitz.Page,
        rendered_width: int,
        rendered_height: int,
    ) -> list[tuple[int, int, int, int]]:
        try:
            tables = page.find_tables()
        except Exception:
            return []
        return PdfParserService._scale_page_bboxes(
            page,
            [table.bbox for table in tables.tables],
            rendered_width,
            rendered_height,
        )

    @staticmethod
    def _scale_page_bboxes(
        page: fitz.Page,
        bboxes: list[tuple[float, float, float, float]],
        rendered_width: int,
        rendered_height: int,
    ) -> list[tuple[int, int, int, int]]:
        page_rect = page.rect
        scale_x = rendered_width / float(page_rect.width or rendered_width)
        scale_y = rendered_height / float(page_rect.height or rendered_height)
        scaled: list[tuple[int, int, int, int]] = []
        for x0, y0, x1, y1 in bboxes:
            x = int(x0 * scale_x)
            y = int(y0 * scale_y)
            w = max(1, int((x1 - x0) * scale_x))
            h = max(1, int((y1 - y0) * scale_y))
            scaled.append((x, y, w, h))
        return scaled

    @staticmethod
    def _merge_regions(regions: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
        if not regions:
            return []

        boxes = [(x, y, x + w, y + h) for x, y, w, h in regions]
        changed = True
        while changed:
            changed = False
            merged: list[tuple[int, int, int, int]] = []
            for box in boxes:
                for index, existing in enumerate(merged):
                    if PdfParserService._boxes_touch(box, existing, gap=24):
                        merged[index] = (
                            min(box[0], existing[0]),
                            min(box[1], existing[1]),
                            max(box[2], existing[2]),
                            max(box[3], existing[3]),
                        )
                        changed = True
                        break
                else:
                    merged.append(box)
            boxes = merged

        boxes.sort(key=lambda item: (item[1], item[0], item[2]))
        return [(x0, y0, x1 - x0, y1 - y0) for x0, y0, x1, y1 in boxes]

    @staticmethod
    def _boxes_touch(
        first: tuple[int, int, int, int],
        second: tuple[int, int, int, int],
        *,
        gap: int,
    ) -> bool:
        return not (
            first[2] + gap < second[0]
            or second[2] + gap < first[0]
            or first[3] + gap < second[1]
            or second[3] + gap < first[1]
        )

    def _is_meaningful_image(self, image_bytes: bytes) -> bool:
        if len(image_bytes) < self.MIN_IMAGE_BYTES:
            return False
        try:
            data = np.frombuffer(image_bytes, dtype=np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        except Exception:
            return False
        if image is None:
            return False
        height, width = image.shape[:2]
        return width >= self.MIN_IMAGE_WIDTH and height >= self.MIN_IMAGE_HEIGHT

    @staticmethod
    def _get_image_size(image_bytes: bytes) -> tuple[int | None, int | None]:
        try:
            data = np.frombuffer(image_bytes, dtype=np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        except Exception:
            return None, None
        if image is None:
            return None, None
        height, width = image.shape[:2]
        return width, height

    @staticmethod
    def _build_image_object_key(image_prefix: str, filename: str) -> str:
        prefix_path = Path(image_prefix)
        parent = prefix_path.parent
        stem = prefix_path.stem if prefix_path.suffix else prefix_path.name
        return str(parent / "image" / stem / filename)

    def _inject_image_references(
        self, markdown: str, backend: str, image_assets: list[PdfImageAsset]
    ) -> str:
        if not markdown:
            return markdown

        pattern = self.PLACEHOLDER_PATTERNS.get(backend)
        remaining = list(image_assets)

        if pattern:

            def replacer(match: re.Match[str]) -> str:
                if not remaining:
                    return ""
                asset = self._pop_matching_asset(match, remaining)
                if asset is None:
                    return ""
                return f"![page-{asset.page_number}-image-{asset.index}]({asset.url})"

            markdown = pattern.sub(replacer, markdown)

        if remaining:
            tail = "\n\n" + "\n\n".join(
                f"![page-{asset.page_number}-image-{asset.index}]({asset.url})"
                for asset in remaining
            )
            markdown = markdown.rstrip() + tail

        return markdown

    def _pop_matching_asset(
        self,
        match: re.Match[str],
        remaining: list[PdfImageAsset],
    ) -> PdfImageAsset | None:
        width = match.groupdict().get("width")
        height = match.groupdict().get("height")
        page = match.groupdict().get("page")

        if width and height:
            target_width = int(width)
            target_height = int(height)
            if target_width < self.MIN_IMAGE_WIDTH or target_height < self.MIN_IMAGE_HEIGHT:
                return None
            target_aspect = target_width / float(target_height)
            best_index = None
            best_score = float("inf")
            for index, asset in enumerate(remaining):
                if not asset.width or not asset.height:
                    continue
                aspect = asset.width / float(asset.height)
                score = abs(aspect - target_aspect) / target_aspect
                if score < best_score:
                    best_score = score
                    best_index = index
            if best_index is not None and best_score <= 0.35:
                return remaining.pop(best_index)
            return None

        if page:
            page_number = int(page)
            for index, asset in enumerate(remaining):
                if asset.page_number == page_number:
                    return remaining.pop(index)
            return None

        return remaining.pop(0)
