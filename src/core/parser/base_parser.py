from .interfaces import IFileParser


class BaseParser(IFileParser):
    """解析器基类"""

    metadata: dict  # 添加类型注解，消除 IDE 对未解析特性的误报警告

    def __init__(self):
        self.metadata = {}

    def validate_stream(self, file_stream: bytes):
        """通用的文件校验逻辑"""
        if not file_stream or len(file_stream) == 0:
            raise ValueError("文件流不可为空")
        return True

    def extract_metadata(self) -> dict:
        return self.metadata