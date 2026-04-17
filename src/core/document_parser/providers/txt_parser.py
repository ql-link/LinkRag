from ..base_parser import BaseParser

class TxtParser(BaseParser):
    """纯文本标准化读取"""
    def parse(self, file_stream: bytes) -> str:
        self.validate_stream(file_stream)
        text = file_stream.decode('utf-8', errors='ignore')
        return text