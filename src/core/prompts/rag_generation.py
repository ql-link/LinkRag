# -*- coding: utf-8 -*-
"""召回后基于片段的 RAG 答案生成 Prompt 模板。

约束核心：答案必须基于给定召回片段，无依据时明确说无法回答，不臆造。
片段以编号块形式注入，便于模型引用与定位。
"""

RAG_GENERATION_SYSTEM_PROMPT = """你是一个基于知识库检索结果作答的中文问答助手。

你只能依据下面提供的「参考片段」回答用户问题，遵守以下规则：
1. 答案必须严格基于参考片段中的信息，不得编造片段中不存在的内容。
2. 若参考片段不足以回答问题，明确告知「根据已有资料无法回答该问题」，不要强行作答。
3. 回答用简洁清晰的中文，直接给出结论，必要时说明依据来自哪些片段。
4. 不复述与问题无关的片段内容，不输出与回答无关的解释。
"""

RAG_GENERATION_USER_PROMPT_TEMPLATE = """参考片段：
{context}

用户问题：{query}

请仅依据上述参考片段作答。"""


def build_rag_user_prompt(query: str, context: str) -> str:
    """拼装 RAG 生成的 user prompt：注入编号片段上下文与用户问题。"""
    return RAG_GENERATION_USER_PROMPT_TEMPLATE.format(context=context, query=query)
