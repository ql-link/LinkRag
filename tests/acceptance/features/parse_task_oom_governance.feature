# 验收契约：解析任务OOM风险治理
# 治理范围：非 MinerU 旁路的解析路径（PDF 非 MinerU 后端 / DOCX / DOC / HTML）
# 不变更：MinerU URL 旁路、document_parsed_log 状态机、对外 MQ 消息契约
# 关键字使用 English Gherkin（Given/When/Then），自然语言断言用中文，便于 pytest-bdd 直接消费。

Feature: 解析任务源文件流式下载与临时文件治理
  作为 toLink-Rag 解析流水线
  我希望源文件以流式方式下载到本地临时文件并在解析后立即清理
  以便单任务内存峰值不再随源文件大小线性增长，为后续消费者横向扩展扫除内存障碍

  Background:
    Given 配置 PARSE_TEMP_DIR = "/tmp/tolink-rag-parse"
    And PARSE_TEMP_DIR 已存在且为空
    And ParseTaskPipeline 已初始化并连接到 MinIO 驱动

  # ==== 主流程：MinerU 旁路保持原状 ====

  Scenario: PDF + MinerU 后端跳过下载走 URL 旁路
    Given payload.file_type == "pdf"
    And payload.pdf_parser_backend == "mineru"
    When ParseTaskPipeline 执行该 payload
    Then ParseSourceIO.download_to_path 未被调用
    And PARSE_TEMP_DIR 中没有创建任何临时文件
    And ParseTaskService.aprocess 入参 source_path 为 None
    And parser_kwargs 包含 source_file_url 字段

  # ==== 主流程：非旁路路径走流式下载 ====

  Scenario Outline: 非旁路文件类型流式下载到临时文件并解析
    Given payload.file_type == "<file_type>"
    And payload.pdf_parser_backend == "<pdf_backend>"
    And 对象存储中存在源文件 size=<size_mb>MB
    When ParseTaskPipeline 执行该 payload
    Then ParseSourceIO.download_to_path 被调用且 dst 路径位于 PARSE_TEMP_DIR 下
    And 底层 storage 使用流式接口（MinIO: download_fileobj / OSS: get_object_to_file）拉取
    And 流式下载过程中进程内不存在容纳整份源文件的 bytes 对象
    And parser.parse 入参为 Path 类型，指向该临时文件
    And 解析返回 markdown 后该临时文件已被 os.unlink 删除
    And markdown 通过 upload_bytes 上传到 md_bucket
    And task 终态 status == SUCCESS

    Examples:
      | file_type | pdf_backend | size_mb |
      | pdf       | docling     | 50      |
      | docx      | mineru      | 500     |
      | doc       | mineru      | 100     |
      | html      | mineru      | 5       |

  Scenario: 临时文件在 markdown 拿到后立即删除而非等到 pipeline 终态
    Given payload.file_type == "docx" size=200MB
    When ParseTaskPipeline 执行至 _parse_file 返回 parse_result
    Then 临时文件已被删除
    And 后续 chunk / 向量索引 / ES 阶段执行时 PARSE_TEMP_DIR 不包含该任务的临时文件

  # ==== 异常路径 ====

  Scenario: 对象存储下载失败归类 SOURCE_FILE_NOT_FOUND 且清理临时文件
    Given payload.file_type == "docx"
    And 对象存储对该 object_key 返回 404
    When ParseTaskPipeline 执行该 payload
    Then task 终态 status == FAILED
    And failure_reason 以 "SOURCE_FILE_NOT_FOUND" 开头
    And PARSE_TEMP_DIR 中不残留任何半成品临时文件
    And parse_result MQ 通知已发送 status=FAILED

  Scenario: 临时盘写满触发新错误码 TEMP_DISK_FULL
    Given payload.file_type == "docx" size=300MB
    And 流式下载过程中底层抛出 OSError errno=ENOSPC
    When ParseTaskPipeline 执行该 payload
    Then task 终态 status == FAILED
    And failure_reason 以 "TEMP_DISK_FULL" 开头
    And failure_reason 不等于 SOURCE_FILE_NOT_FOUND
    And PARSE_TEMP_DIR 中不残留半成品临时文件
    And parse_result MQ 通知已发送 status=FAILED

  Scenario: 解析阶段抛异常时临时文件仍被清理
    Given payload.file_type == "docx" size=100MB
    And 源文件已成功下载到临时文件
    When parser.parse 抛出未预期异常
    Then task 终态 status == FAILED
    And failure_reason 以 "PARSE_ENGINE_FAILED" 开头
    And PARSE_TEMP_DIR 中不残留该任务的临时文件

  Scenario: markdown 上传失败时临时文件已删除不重复清理
    Given payload.file_type == "docx" size=100MB
    And 源文件已成功下载并解析完成
    And 临时文件已在解析后立即删除
    When ParseSourceIO.upload_markdown 抛出存储异常
    Then task 终态 status == FAILED
    And failure_reason 以 "PARSED_FILE_UPLOAD_FAILED" 开头
    And finally 兜底清理不抛 FileNotFoundError

  # ==== 启动清理 ====

  Scenario: worker 启动时 PARSE_TEMP_DIR 存在残留文件被清空
    Given PARSE_TEMP_DIR 在启动前包含残留文件 ["abc.tmp", "def.tmp"]
    When worker 进程启动
    Then PARSE_TEMP_DIR 存在
    And PARSE_TEMP_DIR 内文件数 == 0

  Scenario: worker 启动时 PARSE_TEMP_DIR 不存在则创建
    Given PARSE_TEMP_DIR 路径在启动前不存在
    When worker 进程启动
    Then PARSE_TEMP_DIR 被创建为空目录
    And worker 启动成功不抛错

  # ==== 内存治理约束（治理本质的断言） ====

  Scenario: 非旁路路径不再调用全量 bytes 下载接口
    Given payload 任意非旁路类型
    When ParseTaskPipeline 执行该 payload
    Then storage.download_bytes 在整个调用链中调用次数 == 0
    And storage.download_to_path 调用次数 == 1

  Scenario: parser 协议入参为 Path 不再接受 bytes
    Given 任一已注册的 IFileParser 实现（WordParser / PdfParser / HtmlParser）
    When 用 bytes 类型实参调用 parser.parse(b"...")
    Then 抛出 TypeError 或 AttributeError
    When 用 Path 类型实参调用 parser.parse(Path("/tmp/x"))
    Then 返回 str 类型 markdown

  # ==== 观测日志 ====

  Scenario: 下载完成日志包含文件大小与下载耗时字段
    Given payload.file_type == "docx" size=100MB
    When ParseTaskPipeline 完成流式下载
    Then loguru 日志中存在一条匹配 "source downloaded" 的记录
    And 该记录包含字段 task_id
    And 该记录包含字段 file_size_mb 数值 ≈ 100
    And 该记录包含字段 download_ms 数值 > 0

  Scenario: 解析完成日志包含解析耗时与 markdown 字符数字段
    Given payload.file_type == "docx" size=100MB
    When ParseTaskPipeline 完成 _parse_file
    Then loguru 日志中存在一条匹配 "parse completed" 的记录
    And 该记录包含字段 task_id
    And 该记录包含字段 parse_ms 数值 > 0
    And 该记录包含字段 markdown_chars 数值 > 0

  # ==== 存储驱动双家覆盖 ====

  Scenario: MinIO 驱动实现 download_to_path 走 boto3 download_fileobj
    Given ParseTaskPipeline 使用 MinioStorage
    When 调用 storage.download_to_path(bucket, key, dst)
    Then 底层调用 boto3 client.download_fileobj 而非 get_object().Body.read()
    And dst 文件大小 == 对象存储中对象的实际大小

  Scenario: OSS 驱动实现 download_to_path 走流式接口
    Given ParseTaskPipeline 使用 OssStorage
    When 调用 storage.download_to_path(bucket, key, dst)
    Then 底层调用 OSS SDK 的 get_object_to_file 或等价流式接口
    And dst 文件大小 == 对象存储中对象的实际大小
