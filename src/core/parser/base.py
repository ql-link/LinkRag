from abc import ABC, abstractmethod

class IFileParser(ABC):
    """抽象接口契约"""
    @abstractmethod
    def parse(self, file_stream: bytes) -> str:
        """接收文件流，必须返回 Markdown 格式字符串"""
        pass

class BaseParser(IFileParser):
    """解析器基类"""

    metadata: dict

    def __init__(self):
        self.metadata = {}

    def validate_stream(self, file_stream: bytes):
        """通用的文件校验逻辑"""
        if not file_stream or len(file_stream) == 0:
            raise ValueError("文件流不可为空")
        return True

    def extract_metadata(self) -> dict:
        return self.metadata
