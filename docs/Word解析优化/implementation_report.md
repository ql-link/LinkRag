# Word解析优化 实现报告

记录实际落地内容与对 technical_design.md 的差异，不重复需求与方案。

## 1. 实际改动清单

| 文件 | 改动 |
| :--- | :--- |
| `pyproject.toml` | 主依赖新增 `mammoth>=1.6.0`（venv 实装 1.12.0） |
| `src/core/parser/providers/word_parser.py` | 重写：`parse`/`_is_ooxml`/`_docx_to_html`/`_image_hook`/`_render_html`/`_build_metadata` 六方法，mammoth + 复用 HTML 引擎适配层 |
| `tests/unit/core/parser/test_word_parser.py` | 新增：python-docx 程序化 fixture，16 测试覆盖 acceptance 16 Scenario |
| `docs/architecture/file_parser_module.md`、`docs/guides/deployment.md` | 同步 Word 链路与 mammoth 依赖 |

`src/core/parser/html/*`、`factory.py`、`pipeline.py`、`error_codes.py` 零改动（`git diff --stat src/core/parser/html` 为空）。

## 2. 与 technical_design 的差异

| 项 | TD 设计 | 实际实现 | 原因 |
| :--- | :--- | :--- | :--- |
| `_render_html` 返回值 | TD 7.2.5 述「renderer 存实例供 _build_metadata」 | 返回 `renderer` 且把 markdown 存 `self._last_markdown`，`parse` 取该值返回 | 渲染与 metadata 解耦的等价实现，行为不变 |
| 单表失败测试构造 | TD 10.1 列于 test_word_parser.py | 用 monkeypatch 让 `HtmlTableProcessor._classify_table` 抛错，由其自带 try/except 转原位失败兜底 | 真实 docx 无法稳定触发表格处理异常；失败兜底渲染本身由 HTML 模块既有冻结测试守护，此处只验 WordParser 不崩 + 原位 + 计数 |
| 图片失败测试构造 | TD 10.1 列于 test_word_parser.py | monkeypatch `build_mock_object_url` 返回 None 触发 `_image_hook` 占位分支 | 同上，确定性验证占位与 `image_warning_count` |

以上均为测试构造手段/等价实现，未偏离需求边界、未扩范围、未触碰禁改文件。

## 3. 验证结果

- `tests/unit/core/parser/test_word_parser.py`：16 passed。
- HTML 零回归门禁：`tests/unit/core/parser` + `tests/integration/core/parser` 91 passed；`git diff --stat src/core/parser/html` 为空。
- 代表性 docx 实测：标题层级/原文顺序、加粗、嵌套列表、普通表→标准 MD 表且不含 `### 文档表格数据`、合并单元格表→记录式（`[HTML表格开始：`/`记录 N`/无 `<table`）、内嵌图→`![](mock-minio://`（无 `data:image`）、空流→`文件流不可为空`、legacy .doc/损坏/二进制→`ParseBaseException`。

## 3b. 嵌套列表加固（实测发现后追加）

`word/` 富 docx 实测发现：mammoth 默认把 Word 多级列表样式（List Bullet 2/3、
List Number 2/3）拍平为同级 `<li>`，丢失层级（brief 风险表「复杂 Word 样式映射
不全」的真实体现）。

加固：在 `WordParser` 新增 `_LIST_STYLE_MAP` 常量，`_docx_to_html` 调
`mammoth.convert_to_html` 时传 `style_map=`，把内置多级列表样式映射为真正嵌套
的 `ul/ol>li`。仅追加列表规则，标题/加粗/表格/图片等其余样式仍走 mammoth 默认
映射；基于 numPr/ilvl 的真列表（真实 Word 文档）仍由 mammoth 默认编号解析处理。
**HTML 模块零改动**（渲染器既有嵌套列表渲染能力直接复用）。

验证：富 docx 中 `解析任务 > 一次文档转换的最小调度单元`、`分片 > 用于向量化的
语义块` 正确缩进嵌套；标题/表格/图片不受影响；`test_word_parser.py` 16 passed
（`test_nested_lists` 已强化为真断缩进层级，含三级 bullet 与二级 number）；
HTML 零回归门禁 91 passed，`git diff src/core/parser/html` 为空。

局限：仅覆盖 Word 内置 `List Bullet/Number 1-3` 样式；更深层级或自定义列表样式
名不在映射内时回落 mammoth 默认行为（可读但可能塌平），属可接受范围。

## 4. 遗留风险与后续事项

- mammoth 对 vMerge 单元格文本重复（「用户 用户」），语义不损、RAG 可读，本轮接受；如需去重为后续独立优化。
- 复杂自定义 Word 样式映射依赖 mammoth 默认样式表，异常样式可能降级为普通段落（mammoth messages 计数备查，不阻断）。
- `_image_hook` 通过 `HtmlImageRewriter.build_mock_object_url` 复用同款路径规则（伪 URI `docx-embedded:///{sha1}.{ext}`），与 HTML 图片路径格式一致，image_rewriter 零改动。
- 测试交付阶段建议跑 TD 10.3 全部命令。
