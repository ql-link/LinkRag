import fitz  # PyMuPDF
from ..base_parser import BaseParser

class PdfParser(BaseParser):
    """PDF 坐标提取与排版还原逻辑"""

    def parse(self, file_stream: bytes) -> str:
        self.validate_stream(file_stream)

        # 使用 fitz 从内存字节流中加载 PDF
        doc = fitz.open(stream=file_stream, filetype="pdf")
        markdown_lines = []

        for page_num, page in enumerate(doc):
            # 提取纯文本排版
            text = page.get_text("text")
            if text.strip():
                # 增加 Markdown 格式的页码分隔符，方便后续切片 (Chunking)
                markdown_lines.append(f"## 第 {page_num + 1} 页\n")
                markdown_lines.append(text.strip())

        # 记录关键元数据
        self.metadata['pages_or_length'] = len(doc)
        self.metadata['pdf_info'] = doc.metadata

        # 如果整篇文档没有提取出任何文字（可能是纯扫描件）
        if not markdown_lines:
            markdown_lines.append("> [系统提示] 检测到纯图片/扫描版 PDF，物理提取文本为空。")

        return "\n\n---\n\n".join(markdown_lines)