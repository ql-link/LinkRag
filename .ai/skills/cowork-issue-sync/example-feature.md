# 示例：新增需求（Feature / Improvement）

**标题**：Java 端统一请求日志记录（接口入参 / 耗时 / 状态码）

---

## 背景

`link-api` 目前无统一的请求/响应日志中间件。各接口日志依赖 Service 方法内散点打印，
排查问题时需逐层翻代码。`grep` 关键词后往往跨 3–4 个类才能还原一次请求的完整路径。

现有日志现状（不统一）：
- `UserController`：无入参日志
- `ConfigController`：仅在异常分支打印
- `DatasetController`：部分方法有，部分没有

## 目标 / 本 issue 范围

- [ ] 在 `link-api` 新增 `RequestLoggingFilter`（`OncePerRequestFilter` 实现）
- [ ] 统一记录：请求路径、HTTP 方法、入参（敏感字段脱敏）、响应状态码、耗时（ms）
- [ ] 敏感字段（`password`、`token`、`apiKey`）脱敏后输出，不写原值

## 不做什么

- 不引入分布式链路追踪（TraceId 透传可作独立 issue）
- 不集成 ELK 等外部日志系统
- 不对文件上传接口记录 request body（防止日志过大）

## 影响范围

- `link-api` 模块，新增一个 Filter，不改动 Controller 业务逻辑
- 日志量会有所增加，需评估是否影响磁盘/输出性能

## 改进建议 / 实现思路

继承 `OncePerRequestFilter`，在 `doFilterInternal` 中用 `ContentCachingRequestWrapper`
包装请求，拦截 body；响应完成后统一打印。脱敏可用简单正则替换。

## 风险 / 待确认

- `ContentCachingRequestWrapper` 会在内存中缓存 body，大文件上传接口需排除在外
- 日志级别建议 `DEBUG`，生产环境默认关闭，待与运维确认日志策略

## 验收要点

- [ ] 调用 `POST /user/login`，日志中可见路径、耗时、状态码，`password` 字段脱敏
- [ ] 调用不存在路径，日志中可见 404 及耗时
- [ ] 文件上传接口日志中不出现 body 内容
- [ ] 单测验证脱敏逻辑
