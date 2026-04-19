from __future__ import annotations

from abc import ABC, abstractmethod


class BasePdfBackend(ABC):
    """PDF 解析后端抽象。"""

    name: str

    def __init__(self) -> None:
        self.metadata: dict = {}

    @abstractmethod
    def parse(self, file_stream: bytes, options):
        """将 PDF 字节流解析为 Markdown，并返回可选的二进制资产。"""
