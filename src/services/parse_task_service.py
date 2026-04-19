import time
from src.core.parser.factory import ParserFactory
from src.utils.text_formatter import TextFormatter


class ParseTaskService:
    """核心服务: 提供通用的流式解析逻辑"""

    @staticmethod
    def process_sync(file_stream: bytes, file_type: str, **parser_kwargs) -> dict:
        """接收文件字节流，返回解析结果、元数据和耗时"""
        start_time = time.time()

        # 1. 获取对应的解析器
        parser = ParserFactory.get_parser(file_type, **parser_kwargs)

        # 2. 解析原始文本
        raw_markdown = parser.parse(file_stream)

        # 3. 格式清洗排版
        final_markdown = TextFormatter.clean(raw_markdown)
        metadata = parser.extract_metadata()

        time_cost_ms = int((time.time() - start_time) * 1000)

        return {
            "markdown": final_markdown,
            "metadata": metadata,
            "time_cost_ms": time_cost_ms
        }
