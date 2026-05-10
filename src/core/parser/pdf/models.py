from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.services.storage.base import BaseObjectStorage


@dataclass(slots=True)
class PdfBinaryAsset:
    kind: str  # page / picture / table
    page_number: int
    index: int
    ext: str
    content: bytes
    source_path: str | None = None


@dataclass(slots=True)
class PdfImageAsset:
    page_number: int
    index: int
    object_key: str
    url: str
    width: int | None = None
    height: int | None = None
    source_path: str | None = None


@dataclass(slots=True)
class PdfParseOptions:
    backend: str = "mineru"
    image_bucket: Optional[str] = None
    image_prefix: Optional[str] = None
    storage: Optional[BaseObjectStorage] = None
    docling_force_ocr: bool = False
    mineru_api_url: Optional[str] = None
    mineru_api_key: Optional[str] = None
    mineru_timeout: int = 300
