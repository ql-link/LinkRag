from __future__ import annotations

import importlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.parser.pdf.base import BasePdfBackend
from src.core.parser.pdf.models import PdfBinaryAsset


class OpenDataLoaderBackend(BasePdfBackend):
    """OpenDataLoader 本地后端。

    官方 Python API 只接收文件路径；本次治理后 pipeline 已经把源文件流式下载到本地临时
    文件，这里直接复用该路径，不再额外写一份 ``temp_dir/document.pdf`` 副本。
    """

    name = "opendataloader"
    _PAGE_NUMBER_PATTERN = re.compile(r"page[-_ ]?(\d+)", re.IGNORECASE)

    def parse(self, source: Path | None, options: Any = None) -> tuple[str, list[PdfBinaryAsset]]:
        if source is None:
            # 本 backend 不参与 MinerU URL 旁路；source 缺省视为不可解析。
            self.metadata["opendataloader_backend_error"] = "source path 缺失"
            return "", []
        try:
            opendataloader_pdf = importlib.import_module("opendataloader_pdf")
        except ImportError as exc:
            self.metadata["opendataloader_backend_error"] = (
                "opendataloader-pdf 未安装，请先安装该依赖"
            )
            logger.warning(f"[OpenDataLoader] Python 包未安装: {exc}")
            return "", []

        java_check = self._ensure_java_11_plus()
        if java_check is not None:
            self.metadata["opendataloader_backend_error"] = java_check
            logger.warning(f"[OpenDataLoader] {java_check}")
            return "", []

        try:
            # 仅借用 temp_dir 隔离 output_dir / image_dir；输入 PDF 直接复用 pipeline 已经
            # 落盘的 ``source`` 路径，避免再写一份完整 bytes。
            with tempfile.TemporaryDirectory(prefix="opendataloader-") as temp_dir:
                temp_path = Path(temp_dir)
                output_dir = temp_path / "output"
                image_dir = output_dir / "images"
                output_dir.mkdir(parents=True, exist_ok=True)

                opendataloader_pdf.convert(
                    input_path=[str(source)],
                    output_dir=str(output_dir),
                    format="markdown-with-images",
                    image_output="external",
                    image_dir=str(image_dir),
                    quiet=True,
                )

                markdown_path = self._find_markdown_file(output_dir)
                if markdown_path is None:
                    self.metadata["opendataloader_backend_error"] = "未找到 Markdown 输出文件"
                    return "", []

                markdown = markdown_path.read_text(encoding="utf-8")
                assets = self._collect_image_assets(output_dir, image_dir)
                self.metadata["opendataloader_markdown_file"] = str(
                    markdown_path.relative_to(output_dir)
                )
                self.metadata["opendataloader_image_count"] = len(assets)
                return markdown, assets
        except FileNotFoundError as exc:
            self.metadata["opendataloader_backend_error"] = str(exc)
            logger.error(f"[OpenDataLoader] Java 不可用: {exc}")
            return "", []
        except subprocess.CalledProcessError as exc:
            error_text = (exc.stderr or exc.stdout or exc.output or str(exc)).strip()
            self.metadata["opendataloader_backend_error"] = error_text or str(exc)
            logger.error(f"[OpenDataLoader] CLI 执行失败: {error_text or exc}")
            return "", []
        except Exception as exc:
            self.metadata["opendataloader_backend_error"] = str(exc)
            logger.error(f"[OpenDataLoader] 解析异常: {exc}")
            return "", []

    def _ensure_java_11_plus(self) -> str | None:
        try:
            result = subprocess.run(
                ["java", "-version"],
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError:
            return "未检测到 java 命令，OpenDataLoader 需要 Java 11+"
        except subprocess.CalledProcessError as exc:
            return f"执行 java -version 失败: {exc}"

        version_output = (result.stderr or result.stdout or "").strip()
        major_version = self._parse_java_major_version(version_output)
        self.metadata["opendataloader_java_version"] = (
            version_output.splitlines()[0] if version_output else ""
        )
        if major_version is None:
            return f"无法识别 Java 版本: {version_output}"
        if major_version < 11:
            return f"当前 Java 版本为 {major_version}，OpenDataLoader 官方要求 Java 11+"
        return None

    @classmethod
    def _parse_java_major_version(cls, version_output: str) -> int | None:
        match = re.search(r'version "([^"]+)"', version_output)
        if not match:
            return None
        version = match.group(1)
        if version.startswith("1."):
            parts = version.split(".")
            return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        major = version.split(".", 1)[0]
        return int(major) if major.isdigit() else None

    @staticmethod
    def _find_markdown_file(output_dir: Path) -> Path | None:
        candidates = sorted(output_dir.rglob("*.md"))
        return candidates[0] if candidates else None

    def _collect_image_assets(
        self,
        output_dir: Path,
        image_dir: Path,
    ) -> list[PdfBinaryAsset]:
        if not image_dir.exists():
            return []

        assets: list[PdfBinaryAsset] = []
        next_index = 1
        for image_path in sorted(image_dir.rglob("*")):
            if not image_path.is_file():
                continue
            ext = image_path.suffix.lstrip(".").lower() or "png"
            assets.append(
                PdfBinaryAsset(
                    kind="picture",
                    page_number=self._guess_page_number(image_path.name),
                    index=next_index,
                    ext=ext,
                    content=image_path.read_bytes(),
                    source_path=image_path.relative_to(output_dir).as_posix(),
                )
            )
            next_index += 1
        return assets

    def _guess_page_number(self, filename: str) -> int:
        match = self._PAGE_NUMBER_PATTERN.search(filename)
        if not match:
            return 1
        try:
            return int(match.group(1))
        except ValueError:
            return 1
