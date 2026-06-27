"""Prompt templates used by core LLM-assisted workflows."""

from .conversation_title import (
    CONVERSATION_TITLE_SYSTEM_PROMPT,
    CONVERSATION_TITLE_USER_PROMPT_TEMPLATE,
    build_title_user_prompt,
    clean_title,
    fallback_title_from_query,
)
from .markdown_enhancement import (
    TABLE_PROMPT_TEMPLATE,
    TABLE_SYSTEM_PROMPT,
    VISION_PROMPT_TEMPLATE,
)
from .rag_generation import (
    RAG_GENERATION_SYSTEM_PROMPT,
    RAG_GENERATION_USER_PROMPT_TEMPLATE,
    build_rag_user_prompt,
)

__all__ = [
    "CONVERSATION_TITLE_SYSTEM_PROMPT",
    "CONVERSATION_TITLE_USER_PROMPT_TEMPLATE",
    "RAG_GENERATION_SYSTEM_PROMPT",
    "RAG_GENERATION_USER_PROMPT_TEMPLATE",
    "TABLE_PROMPT_TEMPLATE",
    "TABLE_SYSTEM_PROMPT",
    "VISION_PROMPT_TEMPLATE",
    "build_rag_user_prompt",
    "build_title_user_prompt",
    "clean_title",
    "fallback_title_from_query",
]
