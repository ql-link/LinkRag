# Word解析优化 Feature Info

## 模块定位

Word（.docx）解析混合方案：mammoth 把 docx 转语义 HTML，复用 `docs/HTML解析混合优化/`（commit `b4d2b76` 已交付）的 HTML 渲染引擎（renderer / table_processor / image_rewriter / _clean_soup）产出结构保真 Markdown。docx 无站点样板，跳过 trafilatura 正文定位。唯一新增能力：内嵌图片 → 模拟 MinIO 对象路径（image_rewriter 扩展，开关隔离，HTML 行为不变）。

## 当前阶段

实现完成，待测试交付（implementation_report.md 已出）

## 产物清单

| 产物 | 路径 | 状态 |
| :--- | :--- | :--- |
| Brief | `docs/Word解析优化/brief.md` | 已冻结 |
| Acceptance | `docs/Word解析优化/acceptance.feature` | 已冻结（16 Scenario） |
| Technical Design | `docs/Word解析优化/technical_design.md` | 已冻结（mammoth + 复用 HTML 引擎，6 方法级设计） |
| Implementation Report | `docs/Word解析优化/implementation_report.md` | 已出（TD 差异、验证结果、遗留风险） |

## Acceptance 覆盖情况

- Scenario 总数：16
- 主流程：4（标题层级/顺序、加粗超链接、嵌套列表、表格图片段落 DOM 顺序）
- 表格：3（普通表→MD 表在原位、合并单元格→记录式、单表失败原位记录）
- 图片：2（内嵌图→mock-minio、单图失败占位不阻断）
- 异常与边界：7（非 OOXML Outline 三例、空文件、mammoth 空内容、不改非 Word 链路、不改 pipeline 契约、HTML 模块零回归门禁）

## 冻结信息

- technical_design 冻结时间：2026-05-19（mammoth + 复用 HTML 引擎 6 方法级设计，开发者确认复用方式）
- acceptance 冻结时间：2026-05-19（16 Scenario，开发者审核通过）
- brief 冻结时间：2026-05-19
- 关键决策：
  - 方案：docx → mammoth 语义 HTML → 复用 commit `b4d2b76` HTML 引擎（renderer/table_processor/image_rewriter/_clean_soup 原样），跳过 trafilatura。
  - Q1：legacy `.doc`/非 OOXML 在 `WordParser` 内检测即抛 `ParseBaseException` → `PARSE_ENGINE_FAILED`，不改 factory/错误码/对外契约。
  - Q2：内嵌图经 mammoth `convert_image` 钩子在 Word 适配层生成模拟 MinIO 对象路径作 `<img src>`；HTML 模块（含 image_rewriter）零改动，HTML 28 场景天然零回归。
  - 不引 Pandoc/LLM；不做真实图片上传；不支持 legacy .doc。

## 触发背景

- 时间：2026-05-19
- 现状 `src/core/parser/providers/word_parser.py`（python-docx 手撸）：表格抽到文末非合法 MD、丢原文顺序、合并单元格错乱、内嵌图丢弃、无超链接/嵌套列表保真。
- 实测对比：mammoth docx→语义 HTML 正确输出 rowspan/colspan、按原文顺序、内嵌图 data:base64、无警告；经 HTML 引擎端到端得结构保真 Markdown（简单表→MD 表、合并表→记录式）。Pandoc 实测对 RAG 复杂表格更差（裸 `<table>`/grid-table）、图片本地临时路径、依赖重，已否。
- 方向锁定：mammoth + 复用 HTML 引擎 + 新增内嵌图→模拟 MinIO；不引 Pandoc/LLM；不做真实上传；不支持 legacy .doc。

## 上游材料

- `docs/HTML解析混合优化/`（姊妹模块冻结产物 + 实现 commit `b4d2b76`）
- `src/core/parser/providers/word_parser.py`、`src/core/parser/factory.py`、`src/core/parser/base.py`
- `src/core/parser/html/{renderer,table_processor,image_rewriter,service,models}.py`
- `src/core/pipeline/parse_task/pipeline.py:160-169`（异常→PARSE_ENGINE_FAILED 映射）
