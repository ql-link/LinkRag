"""
Tokenizer 模块
使用 tiktoken 进行 Token 预计算与截断，防止 LLM 输入溢出
"""
from typing import Optional, Tuple

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False


class Tokenizer:
    """Token 计数器与截断工具

    使用 tiktoken 计算 token 数，支持：
    - 统计文本 token 数
    - 按 max_tokens 截断文本
    - 计算可用 token 数（考虑上下文限制）
    """

    DEFAULT_ENCODING = "cl100k_base"  # GPT-4 / GPT-3.5 使用的编码

    def __init__(self, encoding_name: Optional[str] = None):
        self.encoding_name = encoding_name or self.DEFAULT_ENCODING
        self._encoder = None
        self._init_encoder()

    def _init_encoder(self):
        """初始化编码器"""
        if HAS_TIKTOKEN:
            try:
                self._encoder = tiktoken.get_encoding(self.encoding_name)
            except Exception:
                # 回退到简单估算
                self._encoder = None
        else:
            self._encoder = None

    def count_tokens(self, text: str) -> int:
        """计算文本的 token 数

        Args:
            text: 待计算的文本

        Returns:
            token 数量
        """
        if not text:
            return 0

        if self._encoder:
            return len(self._encoder.encode(text))
        else:
            # 简单估算：中文约 2 tokens/字符，英文约 0.25 tokens/字符
            return self._estimate_tokens(text)

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数（无 tiktoken 时使用）"""
        chinese_chars = sum(1 for c in text if ord(c) > 127)
        english_chars = len(text) - chinese_chars
        return int(chinese_chars * 2 + english_chars * 0.25)

    def truncate_text(self, text: str, max_tokens: int) -> Tuple[str, int]:
        """按 max_tokens 截断文本

        Args:
            text: 待截断文本
            max_tokens: 最大 token 数

        Returns:
            (截断后的文本, 移除的 token 数)
        """
        current_tokens = self.count_tokens(text)

        if current_tokens <= max_tokens:
            return text, 0

        if self._encoder:
            tokens = self._encoder.encode(text)
            truncated_tokens = tokens[:max_tokens]
            truncated_text = self._encoder.decode(truncated_tokens)
            return truncated_text, current_tokens - max_tokens
        else:
            # 简单估算后截断
            ratio = max_tokens / current_tokens
            char_limit = int(len(text) * ratio)
            truncated_text = text[:char_limit]
            removed = current_tokens - self.count_tokens(truncated_text)
            return truncated_text, removed

    def calculate_available_tokens(
        self,
        context: str,
        max_model_tokens: int,
        system_prompt: Optional[str] = None,
        reserved_tokens: int = 100,
    ) -> int:
        """计算可用的最大 token 数

        Args:
            context: 上下文文本（如 RAG 检索结果）
            max_model_tokens: 模型最大 token 限制
            system_prompt: 系统提示词（会占用 token）
            reserved_tokens: 保留的安全边界 token 数

        Returns:
            可用于生成的最大 token 数
        """
        context_tokens = self.count_tokens(context)
        system_tokens = self.count_tokens(system_prompt) if system_prompt else 0

        available = max_model_tokens - context_tokens - system_tokens - reserved_tokens

        return max(0, available)

    def truncate_rag_context(
        self,
        context: str,
        max_model_tokens: int,
        system_prompt: Optional[str] = None,
        reserved_tokens: int = 100,
    ) -> str:
        """截断 RAG 上下文，确保不超过模型限制

        Args:
            context: RAG 检索到的上下文
            max_model_tokens: 模型最大 token 限制
            system_prompt: 系统提示词
            reserved_tokens: 保留 token 数

        Returns:
            截断后的上下文
        """
        available = self.calculate_available_tokens(
            context=context,
            max_model_tokens=max_model_tokens,
            system_prompt=system_prompt,
            reserved_tokens=reserved_tokens,
        )

        truncated, _ = self.truncate_text(context, available)
        return truncated
