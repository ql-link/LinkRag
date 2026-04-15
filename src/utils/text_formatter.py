import re

class TextFormatter:
    """Markdown 文本统一清洗/排版工具"""
    @staticmethod
    def clean(md_text: str) -> str:
        # 移除多余的空行
        cleaned = re.sub(r'\n{3,}', '\n\n', md_text)
        return cleaned.strip()