# 这是一个参考样例，展示 acceptance.feature 的写法。
# 真实生成时根据 brief.md 的内容产出，不要照抄此模板。
# 中文 / 英文混合均可，关键是断言可机器验证。

Feature: 文档异步解析
  作为已登录用户
  我希望上传文档后立即返回 task_id
  以便不阻塞我的其他操作，后台异步完成解析

  Background:
    Given 用户 alice 已登录
    And 用户配额未满

  # ==== 主流程 ====

  Scenario: 上传新 PDF 创建解析任务
    When alice 提交文件 "report.pdf" hash=abc123 size=2MB
    Then 系统创建 task=T1
    And task.status == PENDING
    And task.file_hash == "abc123"
    And 接口返回 task_id=T1
    And 5 秒内 MQ topic "parse-task" 收到一条消息 task_id=T1

  Scenario: 解析成功推进状态
    Given task=T1 status=PARSING
    When 解析器返回成功结果 content_length=1024
    Then task.status == PARSED
    And task.result_path 非空
    And MQ topic "parse-completed" 收到一条消息 task_id=T1

  # ==== 幂等与重复处理 ====

  Scenario: 重复上传同一文件返回已有任务
    Given 已存在 task=T1 hash=abc123 status=PARSED
    When alice 再次提交文件 hash=abc123
    Then 接口返回 task_id=T1
    And 不创建新任务
    And 不发送 MQ 消息

  Scenario: MQ 重复投递的消息只处理一次
    Given task=T1 status=PARSED
    When MQ 重复投递 task=T1 的解析消息
    Then 不重新触发解析
    And 不修改 task.status
    And ack 该消息

  # ==== 异常与重试 ====

  Scenario: 可重试异常触发重试
    Given task=T1 status=PARSING retry_count=0
    When 解析器抛出 TransientParseError
    Then task.status 回退到 PENDING
    And task.retry_count == 1
    And 30 秒内重新出现在消费队列

  Scenario: 重试达上限转人工
    Given task=T1 status=PARSING retry_count=2
    When 解析器抛出 TransientParseError
    Then task.status == FAILED
    And task.failure_reason == "MAX_RETRY_EXCEEDED"
    And 不再投递到重试队列

  Scenario: 不可恢复错误直接失败
    Given task=T1 status=PARSING
    When 解析器抛出 PermanentParseError reason="CORRUPT_FILE"
    Then task.status == FAILED
    And task.failure_reason == "CORRUPT_FILE"
    And task.retry_count 不变

  # ==== 边界条件 ====

  Scenario Outline: 不支持的文件类型直接拒绝
    When alice 提交文件后缀 <ext>
    Then 接口返回 400 错误码 UNSUPPORTED_TYPE
    And 不创建任务
    And 不发送 MQ 消息

    Examples:
      | ext  |
      | .exe |
      | .zip |
      | .mp4 |
      | .iso |

  Scenario: 超过大小限制拒绝
    When alice 提交文件 size=51MB
    Then 接口返回 400 错误码 FILE_TOO_LARGE
    And 不创建任务

  Scenario: 配额已满拒绝上传
    Given 用户 alice 配额已满
    When alice 提交任意文件
    Then 接口返回 403 错误码 QUOTA_EXCEEDED
    And 不创建任务
