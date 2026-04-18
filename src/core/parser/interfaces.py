from abc import ABC, abstractmethod

class IFileParser(ABC):
    """抽象接口契约"""
    @abstractmethod
    def parse(self, file_stream: bytes) -> str:
        """接收文件流，必须返回 Markdown 格式字符串"""
        pass