Feature: HTML解析重构
  作为知识库解析服务
  我希望将 HTML 文件稳定转换为 RAG 友好的 Markdown
  以便后续 Markdown 解析、分片和向量化能够保留标题、表格、图片、代码块和上下文顺序

  Background:
    Given HTML 解析使用文档模式
    And 旧 trafilatura HTML 正文抽取路径已停用
    And 不执行真实图片下载
    And 不执行真实 MinIO 上传

  # ==== 主流程 ====

  Scenario: 基础 HTML 结构按 DOM 顺序转换为 Markdown
    Given HTML 内容包含 h1 标题、段落、链接、无序列表和代码块
    When 系统解析该 HTML 内容
    Then Markdown 按原 DOM 顺序包含 "# 主标题"
    And Markdown 包含 "这是正文段落"
    And Markdown 包含 "[接口文档](https://example.com/docs/api)"
    And Markdown 包含 "- 第一项"
    And Markdown 包含 fenced code block 语言 "python"
    And metadata.parse_mode == "document"

  Scenario: 噪声节点不会进入 Markdown
    Given HTML 内容包含 script、style、noscript、template 和正文段落 "有效知识内容"
    When 系统解析该 HTML 内容
    Then Markdown 包含 "有效知识内容"
    And Markdown 不包含 "console.log"
    And Markdown 不包含 ".hidden"
    And Markdown 不包含 "noscript fallback"
    And Markdown 不包含 "template text"

  Scenario: 表格、图片和段落保持原始上下文顺序
    Given HTML 内容顺序为段落 "表格前说明"、table、图片、段落 "表格后说明"
    When 系统解析该 HTML 内容
    Then Markdown 中 "表格前说明" 出现在 Markdown table 之前
    And Markdown table 出现在 Markdown 图片引用之前
    And Markdown 图片引用出现在 "表格后说明" 之前

  # ==== 表格处理 ====

  Scenario: 简单 HTML 表格输出标准 Markdown table
    Given HTML 内容包含表头 "字段" 和 "含义" 的二维 table
    And table 数据行包含 "user_id" 和 "用户 ID"
    When 系统解析该 HTML 内容
    Then Markdown 包含 "| 字段 | 含义 |"
    And Markdown 包含 "| --- | --- |"
    And Markdown 包含 "| user_id | 用户 ID |"
    And parse_result.tables 数量 == 1

  Scenario: rowspan 表格展开后保持字段和值对应
    Given HTML table 第一列单元格 "模块A" rowspan=2
    And 第一行数据包含 "接口" 和 "创建任务"
    And 第二行数据包含 "消息" 和 "发送结果"
    When 系统解析该 HTML 内容
    Then Markdown table 包含一行 "模块A"、"接口"、"创建任务"
    And Markdown table 包含一行 "模块A"、"消息"、"发送结果"
    And Markdown 不包含 "rowspan"
    And Markdown 不包含 "<table"

  Scenario: colspan 和多级表头表格输出可读列名
    Given HTML table 包含 colspan 多级表头 "用户信息"
    And 子表头包含 "姓名" 和 "角色"
    And 数据行包含 "alice" 和 "管理员"
    When 系统解析该 HTML 内容
    Then Markdown table 表头包含 "用户信息 / 姓名"
    And Markdown table 表头包含 "用户信息 / 角色"
    And Markdown table 包含 "alice"
    And Markdown table 包含 "管理员"

  Scenario: 列表单元格不会破坏 Markdown table
    Given HTML table 的一个单元格包含列表项 "读权限" 和 "写权限"
    When 系统解析该 HTML 内容
    Then Markdown table 中该单元格包含 "读权限"
    And Markdown table 中该单元格包含 "写权限"
    And Markdown table 每一行的列数一致

  Scenario: 嵌套表格输出记录式 Markdown
    Given HTML table 的一个单元格包含嵌套 table
    When 系统解析该 HTML 内容
    Then Markdown 包含 "[HTML表格开始："
    And Markdown 包含 "表格类型：记录式表格"
    And Markdown 包含 "表格说明：该 HTML 表格包含嵌套表格"
    And Markdown 包含 "表格结构："
    And Markdown 包含 "记录 1："
    And Markdown 不包含 "\n### 表格："
    And Markdown 不包含 "\n#### 记录"
    And Markdown 不包含 "<table"
    And parse_result.tables 数量 == 0

  Scenario: 图片单元格输出记录式 Markdown
    Given HTML table 的一个单元格包含 img src="/assets/arch.png" alt="架构图"
    When 系统解析该 HTML 内容
    Then Markdown 包含 "[HTML表格开始："
    And Markdown 包含 "表格类型：记录式表格"
    And Markdown 包含 "表格说明：该 HTML 表格包含图片单元格"
    And Markdown 包含 "架构图"
    And Markdown 包含模拟 MinIO 图片路径
    And Markdown 不包含 "\n### 表格："
    And Markdown 不包含 "\n#### 记录"

  Scenario: 大表格不拆分为多个表格片段
    Given HTML 内容包含一个 120 行的普通 table
    When 系统解析该 HTML 内容
    Then Markdown 中只出现 1 个 Markdown table 块
    And metadata.table_count == 1
    And metadata.table_split_count == 0

  Scenario: 单个表格处理失败时输出原位置失败记录
    Given HTML 内容顺序为段落 "失败前"、一个会触发表格处理异常的 table、段落 "失败后"
    When 系统解析该 HTML 内容
    Then Markdown 中 "失败前" 出现在 "表格解析失败：该位置原本是一个 HTML 表格" 之前
    And "表格解析失败：该位置原本是一个 HTML 表格" 出现在 "失败后" 之前
    And Markdown 包含 "失败原因："
    And metadata.table_failure_count == 1
    And 系统不抛出整篇 HTML 解析异常

  # ==== 图片和链接 ====

  Scenario: 相对链接和图片 URL 转为绝对 URL 后生成模拟 MinIO 图片引用
    Given HTML 来源 URL 为 "https://example.com/docs/page.html"
    And HTML 内容包含链接 href="/docs/api"
    And HTML 内容包含图片 src="/assets/arch.png" alt="系统架构图"
    When 系统解析该 HTML 内容
    Then Markdown 包含 "[接口文档](https://example.com/docs/api)"
    And Markdown 包含 "![系统架构图]("
    And Markdown 包含模拟 MinIO 图片路径
    And metadata.image_count == 1
    And metadata.image_upload_count == 0

  Scenario: srcset 图片选择较优候选并生成模拟对象路径
    Given HTML 来源 URL 为 "https://example.com/docs/page.html"
    And HTML 图片包含 src="/img/small.png"
    And HTML 图片包含 srcset="/img/small.png 1x, /img/large.png 2x"
    When 系统解析该 HTML 内容
    Then metadata.images[0].source_url == "https://example.com/img/large.png"
    And Markdown 图片引用包含模拟 MinIO 图片路径

  Scenario: figure 图片保留图注
    Given HTML figure 包含 img alt="流程图"
    And HTML figure 包含 figcaption "图 1：解析流程"
    When 系统解析该 HTML 内容
    Then Markdown 包含 "![流程图]("
    And Markdown 包含 "图 1：解析流程"
    And "![流程图](" 出现在 "图 1：解析流程" 之前

  # ==== 异常与边界 ====

  Scenario: 空 HTML 文件直接失败
    Given HTML 文件内容为空
    When 系统解析该 HTML 内容
    Then 系统抛出解析异常
    And 异常原因包含 "文件流不可为空"

  Scenario: DOM 构建后没有有效内容直接失败
    Given HTML 内容只包含 script、style 和空白节点
    When 系统解析该 HTML 内容
    Then 系统抛出解析异常
    And 异常原因包含 "HTML 正文提取失败"

  Scenario: 图片无法生成模拟对象路径时保留绝对原始引用
    Given HTML 来源 URL 为 "https://example.com/docs/page.html"
    And HTML 图片 src="/assets/broken.png" alt="损坏图片"
    And 模拟 MinIO 路径生成失败
    When 系统解析该 HTML 内容
    Then Markdown 包含 "![损坏图片](https://example.com/assets/broken.png)"
    And metadata.image_warning_count == 1
    And 系统不抛出整篇 HTML 解析异常

  Scenario: HTML 解析重构不改变非 HTML 解析链路
    Given 文件类型为 "pdf"
    When 系统选择解析器
    Then 解析器仍为 PDF 解析器
    And 不使用 HTML 解析服务

  Scenario: HTML 解析重构不改变 pipeline 公共契约
    Given HTML 解析产出 Markdown 成功
    When ParseTaskService 接收该 Markdown
    Then ParseTaskService 返回字段包含 "markdown"
    And ParseTaskService 返回字段包含 "parse_result"
    And ParseTaskService 返回字段包含 "metadata"
    And ParseTaskService 返回字段包含 "time_cost_ms"
