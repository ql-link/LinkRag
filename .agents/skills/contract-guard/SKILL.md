---
name: contract-guard
description: 在技术设计与代码实现阶段校验是否违反跨模块公共契约，并提醒同步更新 middleware_contract.md。
when_to_use: "当技术设计或代码实现涉及 MySQL、Redis、MQ、OSS 等中间件的公共约定，或需要检查是否违反跨模块契约时激活。触发示例：'检查一下有没有违反公共约定'、'这个改动会影响中间件吗'、'新增的表字段是否符合规范'"
---

# Contract Guard

## 目的

确保新功能或改造不会破坏 MySQL、Redis、MQ、OSS、API 等公共约定。

## 必读文件

1. `docs/architecture/middleware_contract.md`
2. 当前模块当前期次目录 `technical_design.md`（若存在）
3. 当前期次相关代码改动

## 检查清单

- 是否新增了公共字段或通用表结构规则
- 是否新增了 Redis key 命名或 TTL 规则
- 是否新增了 MQ topic、queue、group 或消息结构规则
- 是否新增了 OSS 路径、公私有访问规则
- 是否修改了统一接口响应、错误码、日志或追踪约定

## 输出要求

- 若只复用现有约定，说明“未新增公共契约”
- 若新增或修改公共契约，提醒同步更新 `middleware_contract.md`
