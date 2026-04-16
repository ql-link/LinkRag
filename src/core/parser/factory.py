from .providers.word_parser import WordParser
from .providers.txt_parser import TxtParser
from .providers.pdf_parser import PdfParser  # 新增引入
from .providers.html_parser import HtmlParser  # 新增引入
from ..exceptions import UnsupportedFormatError


class ParserFactory:
    """格式分发工厂"""

    @staticmethod
    def get_parser(file_type: str):
        ext = file_type.lower()
        if ext in ['docx', 'doc']:
            return WordParser()
        elif ext == 'txt':
            return TxtParser()
        elif ext == 'pdf':  # 开启 PDF 路由
            return PdfParser()
        elif ext in ['html', 'htm']:  # 开启 HTML 路由
            return HtmlParser()
        else:
            raise UnsupportedFormatError(f"不支持的格式: {ext}")