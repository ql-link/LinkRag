---
name: doc-maintenance-sync
description: 当修改 AGENTS.md/CLAUDE.md、docs/api、docs/internals、docs/ops、docs/contributing.md，或代码变更影响这些文档记录的架构、API、错误码、数据模型、解析器、分片、向量化、命名、数据库结构时，检查并同步更新对应文档，保证项目文档自动维护。
when_to_use: "当用户要求修改项目文档，或代码/配置/数据库/MQ/API/解析器/分片/向量化改动会导致 docs 下的架构、约定、参考资料、计划说明不准确时激活。触发示例：'改了 API 记得更新文档'、'新增错误码'、'调整数据模型'、'修改解析器结构'、'更新 AGENTS'、'同步文档'、'维护项目说明'"
---

# Documentation Maintenance Sync

## 目标

让项目文档跟随真实代码和已维护文档自动同步，避免 `AGENTS.md` / `CLAUDE.md`、`docs/api/`、`docs/internals/`、`docs/ops/`、`docs/contributing.md` 之间出现过期说明。

本 skill 不是要求每次改代码都重写全部文档，而是要求在相关契约变化时做最小必要同步。

## 触发规则

在以下情况必须使用本 skill：

1. 修改 `AGENTS.md`
2. 修改 `docs/api/`、`docs/internals/`、`docs/ops/`、`docs/contributing.md` 下的文档
3. 新增、删除、重命名、移动源码、脚本、测试、Skill 或配置入口，导致项目结构文档不准确
4. 修改 HTTP API、MQ topic/message、错误码、异常、数据库表结构、Pydantic/ORM 模型
5. 修改解析器、分片、向量化、向量存储等模块边界、流程、配置或扩展方式
6. 修改命名、配置、数据库、测试、MQ 等项目级约定

以下情况一般不需要同步文档：

1. 只修复局部实现 bug，且没有改变对外接口、模块边界、配置、数据结构或使用方式
2. 只调整测试内部 Mock、断言或临时数据
3. 只修改注释、格式化或日志文案，且不影响文档描述

## 文档映射

按变更内容选择对应文档，不要无差别更新所有文件。

| 变更内容 | 必查文档 |
| --- | --- |
| Agent 入口、阅读路径、文档目录职责 | `AGENTS.md` |
| 项目目录、核心文件、Skill 列表 | `docs/internals/project_structure.md` |
| 解析器抽象、PDF 后端、解析器选择策略 | `docs/internals/file_parser.md` |
| 分片策略、Chunk 结构、切分流水线 | `docs/internals/chunking.md` |
| 向量化、嵌入、Qdrant、向量存储编排 | `docs/internals/vectorization.md` |
| 命名规则、配置规则、数据库初始化来源 | `docs/internals/naming_conventions.md` |
| API 路由、请求/响应、MQ 消息契约 | `docs/api/http_contracts.md` |
| 错误码、异常类型、失败通知语义 | `docs/api/error_codes.md` |
| ORM、Pydantic、数据库表字段、核心业务模型 | `docs/api/schemas/mysql.md` |
| 当前 feature 的 brief / acceptance / 技术方案 / 实施报告 | `.specs/<feature>/` |

## 同步步骤

1. 先识别本次变更影响的契约类型：架构、API、错误码、数据模型、配置、流程或计划。
2. 按“文档映射”读取最少必要文档。
3. 对照真实代码或真实配置，不从记忆补写不确定内容。
4. 只更新失效段落，保持原文档结构和粒度。
5. 新增文档时，同步更新 `docs/README.md` 的入口。
6. 若新增、删除、移动非 `docs/` 核心目录或 Skill，同时检查 `docs/internals/project_structure.md`。
7. 完成后用 `rg` 或 `git diff` 检查是否仍有旧名称、旧 topic、旧路径或旧字段残留。

## 约束

- 不要在参考文档中写入 `.env`、密钥、Token、真实账号密码或服务器私密凭据。
- 不要把 `AGENTS.md` 重新膨胀成完整知识库；它只保留入口和阅读路径。
- 不要为了文档同步引入与用户请求无关的架构重写。
- 不要把测试报告、一次性排障记录写入稳定架构文档；这类内容应放在 PR 描述或 `.specs/<feature-name>/implementation_report.md`（合并后清理）。
- 以真实代码、`scripts/db/init.sql`、`src/config.py`、`.env.example` 和当前文档为准。

## 最终回复

最终回复需说明：

1. 同步更新了哪些文档
2. 为什么这些文档需要同步
3. 是否运行了校验命令或测试
