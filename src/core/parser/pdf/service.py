from __future__ import annotations

import mimetypes
import re
from dataclasses import asdict
from pathlib import Path

import fitz


from src.core.parser.pdf.backends.mineru_backend import MinerUBackend
from src.core.parser.pdf.backends.naive_backend import NaivePdfBackend
from src.core.parser.pdf.models import PdfBinaryAsset, PdfImageAsset, PdfParseOptions


class PdfParserService:
    PLACEHOLDER_PATTERNS = {
        "naive": re.compile(r"\*\*==> picture .*? intentionally omitted <==\*\*"),
        "docling": re.compile(r"<!-- image -->"),
    }


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
                metadata["pdf_parser_attempts"].append({
                    "backend": backend_name,
                    "success": False,
                    "reason": "unsupported backend",
                })
                continue

            markdown, binary_assets = backend_instance.parse(file_stream, options)
            metadata.update(backend_instance.metadata)
            if markdown and markdown.strip():
                selected_backend = backend_name
                metadata["pdf_parser_attempts"].append({"backend": backend_name, "success": True})
                break
            metadata["pdf_parser_attempts"].append({
                "backend": backend_name,
                "success": False,
                "reason": backend_instance.metadata.get(f"{backend_name}_backend_error", "empty result"),
            })

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
                placeholder_count=placeholder_count,
                binary_assets=binary_assets,
            )
            markdown = self._inject_image_references(markdown, metadata["pdf_parser_backend"], image_assets)
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
        placeholder_count: int,
        binary_assets: list[PdfBinaryAsset],
    ) -> list[PdfImageAsset]:
        suffix = Path(options.image_prefix).suffix
        base_prefix = options.image_prefix[:-len(suffix)] if suffix else options.image_prefix
        image_assets: list[PdfImageAsset] = []

        # 优先使用 Docling 已提取的图片/表格/页图资产
        if binary_assets:
            for asset in binary_assets:
                object_key = (
                    f"{base_prefix}_assets/"
                    f"{asset.kind}-page-{asset.page_number:03d}-{asset.index:02d}.{asset.ext}"
                )
                content_type = mimetypes.types_map.get(f".{asset.ext}", "image/png")
                options.storage.upload_bytes(
                    bucket=options.image_bucket,
                    object_key=object_key,
                    content=asset.content,
                    content_type=content_type,
                )
                url = options.storage.build_object_url(options.image_bucket, object_key)
                image_assets.append(
                    PdfImageAsset(
                        page_number=asset.page_number,
                        index=asset.index,
                        object_key=object_key,
                        url=url,
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
                object_key = f"{base_prefix}_assets/page-{page_index:03d}-image-{image_index:02d}.{ext}"
                content_type = mimetypes.types_map.get(f".{ext}", "image/png")
                options.storage.upload_bytes(
                    bucket=options.image_bucket,
                    object_key=object_key,
                    content=image_bytes,
                    content_type=content_type,
                )
                url = options.storage.build_object_url(options.image_bucket, object_key)
                image_assets.append(PdfImageAsset(page_number=page_index, index=image_index, object_key=object_key, url=url))

        # 如果 PDF 没有内嵌图片（常见于纯矢量页/扫描页），但 Markdown 有图片占位符，
        # 则按页渲染为图片上传，确保 Markdown 可引用可视内容。
        if not image_assets and placeholder_count > 0:
            for page_index, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_bytes = pix.tobytes("png")
                object_key = f"{base_prefix}_assets/page-{page_index:03d}-render.png"
                options.storage.upload_bytes(
                    bucket=options.image_bucket,
                    object_key=object_key,
                    content=image_bytes,
                    content_type="image/png",
                )
                url = options.storage.build_object_url(options.image_bucket, object_key)
                image_assets.append(PdfImageAsset(page_number=page_index, index=1, object_key=object_key, url=url))

        return image_assets

    def _inject_image_references(self, markdown: str, backend: str, image_assets: list[PdfImageAsset]) -> str:
        if not markdown or not image_assets:
            return markdown

        pattern = self.PLACEHOLDER_PATTERNS.get(backend)
        remaining = list(image_assets)

        if pattern:
            def replacer(_: re.Match[str]) -> str:
                if not remaining:
                    return ""
                asset = remaining.pop(0)
                return f"![page-{asset.page_number}-image-{asset.index}]({asset.url})"

            markdown = pattern.sub(replacer, markdown)

        if remaining:
            tail = "\n\n" + "\n\n".join(
                f"![page-{asset.page_number}-image-{asset.index}]({asset.url})" for asset in remaining
            )
            markdown = markdown.rstrip() + tail

        return markdown

