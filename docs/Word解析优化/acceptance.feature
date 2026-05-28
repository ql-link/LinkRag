Feature: Word解析优化
  作为知识库解析服务
  我希望把 .docx 经 mammoth 转语义 HTML 后复用 HTML 渲染引擎转为结构保真 Markdown
  以便后续分片与向量化能保留标题、嵌套列表、表格、图片与原文顺序，
  且与 HTML 解析输出风格一致、不破坏 HTML 模块既有行为

  Background:
    Given Word 解析经 mammoth 把 .docx 转为语义 HTML
    And 最终 Markdown 由复用的 HTML 渲染引擎产出（renderer/table_processor/image_rewriter 原样）
    And docx 无站点样板，跳过 trafilatura 正文定位
    And 内嵌图片由 Word 适配层 mammoth 图片钩子转为模拟 MinIO 对象路径
    And 不执行真实图片下载与 MinIO 上传
    And 入口 WordParser.parse(file_stream: bytes) -> str，调用方与 ParseTaskService 不变

  # ==== 主流程 ====

  Scenario: Word 标题按层级与原文顺序转为 Markdown
    Given docx 含 Heading 1 "产品白皮书"、Heading 2 "一、概述"、Heading 3 "1.1 背景"
    When 系统解析该 docx
    Then Markdown 包含 "# 产品白皮书"
    And Markdown 包含 "## 一、概述"
    And Markdown 包含 "### 1.1 背景"
    And "# 产品白皮书" 出现在 "## 一、概述" 之前
    And "## 一、概述" 出现在 "### 1.1 背景" 之前

  Scenario: 段落、加粗与超链接转为 Markdown
    Given docx 段落为 "本文介绍系统架构"
    And 段落含加粗文本 "重点说明"
    And 段落含超链接文本 "官方文档" 指向 "https://example.com/docs"
    When 系统解析该 docx
    Then Markdown 包含 "本文介绍系统架构"
    And Markdown 包含 "**重点说明**"
    And Markdown 包含 "[官方文档](https://example.com/docs)"

  Scenario: 嵌套项目符号与编号列表转为 Markdown 列表
    Given docx 含项目符号列表项 "第一点" 及其子项 "子项 A"
    And docx 含编号列表项 "步骤一"
    When 系统解析该 docx
    Then Markdown 包含 "- 第一点"
    And Markdown 包含 "子项 A" 且其缩进层级低于 "第一点"
    And Markdown 包含 "1. 步骤一"

  Scenario: 表格、图片与段落保持原文 DOM 顺序
    Given docx 顺序为段落 "表格前说明"、一个二维表格、一张内嵌图片、段落 "表格后说明"
    When 系统解析该 docx
    Then Markdown 中 "表格前说明" 出现在 Markdown 表格之前
    And Markdown 表格出现在 Markdown 图片引用之前
    And Markdown 图片引用出现在 "表格后说明" 之前

  # ==== 表格 ====

  Scenario: 普通二维表格输出标准 Markdown 表格且在原文位置
    Given docx 含表头 "字段" 和 "说明" 的二维表格
    And 数据行包含 "user_id" 和 "用户ID"
    When 系统解析该 docx
    Then Markdown 包含 "| 字段 | 说明 |"
    And Markdown 包含 "| --- | --- |"
    And Markdown 包含 "| user_id | 用户ID |"
    And Markdown 不包含 "### 文档表格数据"
    And metadata.table_count == 1

  Scenario: 合并单元格表格输出记录式 Markdown
    Given docx 含一个纵向合并单元格（vMerge）的表格
    When 系统解析该 docx
    Then Markdown 包含 "[HTML表格开始："
    And Markdown 包含 "表格类型：记录式表格"
    And Markdown 包含 "记录 1："
    And Markdown 不包含 "<table"
    And metadata.record_table_count >= 1

  Scenario: 单个表格处理失败时输出原位置失败记录
    Given docx 顺序为段落 "失败前"、一个会触发表格处理异常的表格、段落 "失败后"
    When 系统解析该 docx
    Then Markdown 中 "失败前" 出现在表格失败记录之前
    And 表格失败记录出现在 "失败后" 之前
    And metadata.table_failure_count == 1
    And 系统不抛出整篇解析异常

  # ==== 图片 ====

  Scenario: 内嵌图片转为模拟 MinIO 对象路径
    Given docx 含一张内嵌图片
    When 系统解析该 docx
    Then Markdown 包含模拟 MinIO 图片路径
    And Markdown 图片引用形如 "![](mock-minio://"
    And Markdown 不包含 "data:image"
    And metadata.image_count == 1

  Scenario: 单张图片对象路径生成失败时保留可读占位
    Given docx 含一张无法生成模拟对象路径的内嵌图片
    When 系统解析该 docx
    Then Markdown 保留该图片的可读占位引用
    And metadata.image_warning_count == 1
    And 系统不抛出整篇解析异常

  # ==== 异常与边界 ====

  Scenario Outline: 非 OOXML 输入快速失败
    Given 待解析文件为 "<场景>"
    When 系统解析该文件
    Then 系统抛出解析异常
    And 失败按 PARSE_ENGINE_FAILED 路径处理
    And 不静默产出空 Markdown
    And 不新增 Word 专用错误码

    Examples:
      | 场景                          |
      | legacy .doc 旧 OLE 二进制文件 |
      | 损坏的非 zip 文件             |
      | 非 docx 的任意二进制内容       |

  Scenario: 空文件流直接失败
    Given Word 文件内容为空
    When 系统解析该文件
    Then 系统抛出解析异常
    And 异常原因包含 "文件流不可为空"

  Scenario: mammoth 转换后无有效内容时失败
    Given docx 经 mammoth 转换后无任何有效正文
    When 系统解析该 docx
    Then 系统抛出解析异常
    And 失败按 PARSE_ENGINE_FAILED 路径处理

  Scenario: Word 解析优化不改变非 Word 解析链路
    Given 文件类型为 "pdf"
    When 系统选择解析器
    Then 解析器仍为 PDF 解析器
    And 文件类型为 "html" 时仍为 HTML 解析器
    And 不使用 Word 解析服务

  Scenario: Word 解析优化不改变 pipeline 公共契约
    Given Word 解析产出 Markdown 成功
    When ParseTaskService 接收该 Markdown
    Then ParseTaskService 返回字段包含 "markdown"
    And ParseTaskService 返回字段包含 "parse_result"
    And ParseTaskService 返回字段包含 "metadata"
    And ParseTaskService 返回字段包含 "time_cost_ms"

  Scenario: 复用 HTML 引擎不改其行为（HTML 模块零回归）
    Given 本模块不修改 src/core/parser/html 下任何文件
    When 运行 HTML 模块既有单测与集成回归
    Then HTML 既有 28 个验收场景全部通过
    And HTML 解析行为与 commit b4d2b76 一致
