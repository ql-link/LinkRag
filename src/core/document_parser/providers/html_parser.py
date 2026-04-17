import trafilatura
from ..base_parser import BaseParser
from src.core.exceptions import ParseBaseException

class HtmlParser(BaseParser):
    """网页去噪提取正文逻辑"""

    def parse(self, file_stream: bytes) -> str:
        self.validate_stream(file_stream)

        # HTML 通常需要先解码为字符串，忽略无法解码的脏字符
        html_content = file_stream.decode('utf-8', errors='ignore')

        # 使用 trafilatura 提取正文，并直接转为 Markdown
        result = trafilatura.extract(
            html_content,
            output_format='markdown',
            include_formatting=True,  # 保留加粗、斜体等内建格式
            include_links=True  # 保留超链接
        )

        if not result:
            # 对应处理策略：如果全是广告脚本导致提取失败，抛出异常阻断
            raise ParseBaseException("HTML 正文提取失败：未找到有效正文内容或噪音过大")

        # 粗略估算长度指标（假设约 500 字符为一页的阅读量）
        self.metadata['pages_or_length'] = (len(result) // 500) + 1

        return result