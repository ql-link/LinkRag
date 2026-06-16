from .providers.word_parser import WordParser
from .providers.pdf_parser import PdfParser
from .providers.html_parser import HtmlParser
from src.core.parser.exceptions import UnsupportedFormatError


class ParserFactory:
    """格式分发工厂"""

    @staticmethod
    def get_parser(file_type: str, **kwargs):
        ext = file_type.lower()
        if ext in ["docx", "doc"]:
            return WordParser()
        elif ext == "pdf":
            return PdfParser(**kwargs)
        elif ext in ["html", "htm"]:
            return HtmlParser(**kwargs)
        else:
            raise UnsupportedFormatError(f"不支持的格式: {ext}")
