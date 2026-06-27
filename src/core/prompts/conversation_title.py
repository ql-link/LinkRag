# -*- coding: utf-8 -*-
"""会话标题生成 Prompt 模板与清洗工具。

会话首轮问答时，Python 基于用户 ``query`` 生成简短中文标题，随 ``chat_turn.title`` 上报供
Java 条件落库、并通过 SSE ``conversation_title`` 事件即时回前端。LLM 标题不可用（失败/超时/
空）时回落 ``fallback_title_from_query``——把原先 Java 端「首问截断临时标题」这层地板搬到
Python，保证首轮一定能命名会话、不停在默认「新对话」。
"""

# 标题清洗 / 截断的最大字符数。LLM prompt 已约束 ≤约 20 字，此处再硬截断兜底；
# Java 侧另按列宽（255）截断，本值远小于列宽，仅为产出短标题。
TITLE_MAX_CHARS = 30

# 标题生成时携带的 query 最大字符数，避免超长提问占用过多输入 token。
TITLE_QUERY_INPUT_MAX_CHARS = 500

# 标题生成的最大输出 token。标题本身仅几十 token，但本轮对话模型可能是**推理模型**
# （如 mimo-v2.5：先思考数百~上千 token 才吐正文）；给太小（如 32）会在思考阶段就被截断、
# 可见正文为空 → 标题回落首问截断。故留足思考预算；超出仍回落兜底。
TITLE_MAX_OUTPUT_TOKENS = 2048

# 包裹型引号/书名号：清洗时若标题被这些成对符号整体包裹则剥除。
_WRAPPING_PAIRS = (
    ('"', '"'),
    ("'", "'"),
    ("“", "”"),
    ("‘", "’"),
    ("「", "」"),
    ("『", "』"),
    ("《", "》"),
)

# 标题结尾若为这些标点则去除（标题不需要句末标点）。
_TRAILING_PUNCT = "。．.，,、；;：:！!？?~～…"


CONVERSATION_TITLE_SYSTEM_PROMPT = """你是会话标题生成助手。请根据用户的提问生成一个简洁的中文标题，概括这次对话的主题。

要求：
1. 标题不超过 20 个字。
2. 直接概括主题，不要照抄整句提问，也不要回答问题。
3. 只输出标题本身，不要加引号、书名号、结尾标点，也不要任何解释或前缀。"""

CONVERSATION_TITLE_USER_PROMPT_TEMPLATE = """用户提问：
{query}

请输出这次对话的标题。"""


def build_title_user_prompt(query: str) -> str:
    """拼装标题生成的 user prompt：注入（截断后的）用户提问。"""
    snippet = query.strip()[:TITLE_QUERY_INPUT_MAX_CHARS]
    return CONVERSATION_TITLE_USER_PROMPT_TEMPLATE.format(query=snippet)


def clean_title(raw: str | None) -> str | None:
    """清洗 LLM 产出的标题：去空白、剥包裹引号、压平换行、去结尾标点、截断。

    清洗后为空返回 ``None``（由调用方回落 :func:`fallback_title_from_query`）。
    """
    if not raw:
        return None
    # 压平换行/制表为单空格，再合并多余空白。
    title = " ".join(raw.split())
    # 反复剥除成对包裹符号（可能嵌套，如 ``"「标题」"``）。
    changed = True
    while changed and title:
        changed = False
        for left, right in _WRAPPING_PAIRS:
            if len(title) >= 2 and title.startswith(left) and title.endswith(right):
                title = title[1:-1].strip()
                changed = True
    title = title.rstrip(_TRAILING_PUNCT).strip()
    title = title[:TITLE_MAX_CHARS].strip()
    return title or None


def fallback_title_from_query(query: str) -> str:
    """首问截断兜底标题：取 query 清洗后的前若干字，必返回非空字符串。

    供 LLM 标题不可用时回落，以及前置失败（模型未解析、无法调 LLM）时直接使用。
    query 经上游校验非空白，理论上截断后非空；极端全标点等情形兜底为「新对话」。
    """
    snippet = " ".join(query.split())
    snippet = snippet.rstrip(_TRAILING_PUNCT).strip()[:TITLE_MAX_CHARS].strip()
    return snippet or "新对话"
