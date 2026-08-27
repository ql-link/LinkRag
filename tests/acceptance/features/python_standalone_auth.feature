Feature: Java 登录 Token 直通 Python
  作为已在 Java 登录的用户
  我希望携带 Java 返回的同一枚 access token 访问 Python 用户态接口
  以便无需再向 Java 换取第二枚召回 token

  Background:
    Given Java 是唯一登录和 access token 签发方
    And Python 配置了 Java access token 的 RS256 公钥
    And Python 可读取共享用户和数据集事实

  # ==== 主流程 ====

  Scenario: 同一枚登录 token 同时访问 Java 与 Python
    Given 启用用户 10000 已在 Java 登录并取得 access token T1
    When 用户携带 T1 访问 Java 受保护接口和 Python RAG 接口
    Then 两个接口都把当前用户识别为 10000
    And Python 不请求 Java 的 token 校验或召回换票接口

  Scenario: Java 停止服务后已签发 token 仍可访问 Python
    Given 启用用户 10000 持有未过期的 access token T1
    And Java 服务当前不可用
    When 用户携带 T1 访问 Python Recall 接口
    Then Python 返回非鉴权错误的业务响应
    And Python 不建立到 Java 的网络请求

  # ==== Token 拒绝 ====

  Scenario Outline: 非法 Java access token 在业务执行前被拒绝
    Given 用户携带一枚 <invalid_reason> 的 Java access token
    When 用户访问任一 Python 用户态接口
    Then 接口返回 HTTP 401 和错误码 ACCESS_TOKEN_UNAUTHORIZED
    And 召回或 Wiki 业务执行次数等于 0

    Examples:
      | invalid_reason |
      | RS256 签名被篡改 |
      | 已过期 |
      | issuer 错误 |
      | audience 不包含 Python API |
      | token_use 不是 access |

  Scenario Outline: 非法用户主体在业务执行前被拒绝
    Given Java access token 的 sub 为 <subject>
    When 用户访问任一 Python 用户态接口
    Then 接口返回 HTTP 401 和错误码 ACCESS_TOKEN_UNAUTHORIZED
    And 召回或 Wiki 业务执行次数等于 0

    Examples:
      | subject |
      | 缺失 |
      | 非数字 |
      | 0 |
      | 负数 |

  Scenario: 用户被禁用后未过期 token 立即失效
    Given 用户 10000 持有未过期的 access token T1
    And 共享用户事实中用户 10000 的状态已变为禁用
    When 用户携带 T1 访问 Python RAG 接口
    Then 接口返回 HTTP 401 和错误码 ACCESS_TOKEN_UNAUTHORIZED
    And RAG pipeline 执行次数等于 0

  Scenario: 管理员降级后未过期 access token 不再具有管理员权限
    Given access token T1 中用户 10000 的角色快照为 ADMIN
    And 共享用户事实中用户 10000 的当前角色已变为 USER
    When 用户携带 T1 通过 Python 管理员鉴权依赖
    Then 鉴权返回 HTTP 403

  # ==== 资源授权 ====

  Scenario: 显式请求本人有效数据集时继续执行业务
    Given 用户 10000 拥有 ACTIVE 数据集 10 和 20
    When 用户携带有效 access token 请求数据集 10
    Then Python 将最终数据集范围解析为 10
    And 业务请求中的 user_id 等于 10000

  Scenario: 省略数据集时只展开本人全部有效数据集
    Given 用户 10000 拥有 ACTIVE 数据集 10 和 20
    And 用户 20000 拥有 ACTIVE 数据集 30
    When 用户 10000 携带有效 access token 且省略 dataset_ids
    Then Python 将最终数据集范围解析为 10 和 20
    And 最终范围不包含 30

  Scenario: 请求其他用户数据集时拒绝且不执行召回
    Given 数据集 30 属于用户 20000
    When 用户 10000 携带有效 access token 请求数据集 30
    Then 接口返回 HTTP 403 和错误码 RECALL_SCOPE_FORBIDDEN
    And 召回 pipeline 执行次数等于 0

  Scenario: 请求已删除或非 ACTIVE 数据集时拒绝
    Given 数据集 10 属于用户 10000 但当前不可用
    When 用户 10000 携带有效 access token 请求数据集 10
    Then 接口返回 HTTP 403 和错误码 RECALL_SCOPE_FORBIDDEN
    And 召回 pipeline 执行次数等于 0

  # ==== 安全边界 ====

  Scenario: Java logout 不提前撤销 Python 中未过期 JWT
    Given 用户 10000 持有距离过期还有 30 分钟的 access token T1
    And Java 已注销 T1 对应的 Sa-Token 登录态
    And 用户 10000 当前仍为启用状态
    When 用户携带 T1 访问 Python Recall 接口
    Then Python 仍通过 token 身份验证
    And T1 到达 exp 后再次访问返回 HTTP 401

  Scenario: 新 token 接入后保留原有 RAG 并发保护
    Given 用户 10000 已占满允许的 RAG 并发流数
    When 用户携带有效 access token 再建立一个 RAG 流
    Then 接口返回 HTTP 429 和错误码 RECALL_RATE_LIMITED
    And 不创建新的 RAG 生产者任务

  Scenario: 安全日志不泄露凭证
    Given 用户发送一枚无法通过验签的 access token T1
    When Python 记录 token 拒绝事件
    Then 日志包含 request_id 和拒绝类型
    And 日志不包含 T1、Authorization 原文、私钥或公钥正文
