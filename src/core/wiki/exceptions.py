"""Wiki 标题树领域操作使用的异常类型。"""


class WikiTreeBuildError(ValueError):
    """ParseResult 与 Chunk 输入无法构成确定性 Wiki 树。"""


class WikiCursorError(ValueError):
    """Wiki 游标格式错误、已经过期或绑定到其他请求。"""
