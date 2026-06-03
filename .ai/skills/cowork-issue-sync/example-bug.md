# 示例：修复 Bug

**标题**：`POST /dataset/{id}/file` 上传文件后 OSS 路径写入空字符串

---

## 背景

文件上传流程由 `DocumentFileService.uploadFile()` 处理，上传成功后将 OSS 路径写入
`knowledge_file.oss_path`。近期发现部分文件记录的 `oss_path` 为空字符串，导致后续
Python 侧解析任务找不到原文件。

## 问题描述

上传文件成功（HTTP 200）后，`knowledge_file.oss_path` 字段写入空字符串而非实际路径。

## 复现路径

1. 以合法用户调用 `POST /dataset/{id}/file`，上传任意 PDF 文件
2. 查询 `knowledge_file` 表对应记录
3. 观察 `oss_path` 字段值为 `""`

## 预期行为

`oss_path` 写入 OSS 返回的完整对象路径，如 `datasets/42/files/uuid.pdf`。

## 实际行为

`oss_path` 为空字符串 `""`；OSS 上文件实际已存在，仅路径未落库。

## 影响范围

- 受影响接口：`POST /dataset/{id}/file`
- 受影响记录：上传时间段内所有 `oss_path = ""` 的 `knowledge_file` 行
- 下游：Python 解析任务因路径为空无法拉取原文件，任务失败

## 相关位置

- `link-service/.../DocumentFileServiceImpl.uploadFile()`
- `link-mapper/.../KnowledgeFileMapper`
- `knowledge_file.oss_path` 字段

## 建议修复方向

初步怀疑 `OssClient.upload()` 返回值未正确赋给局部变量，导致写入了默认空值。
需核查 `uploadFile()` 中 OSS 返回路径的赋值链路。

## 验收要点

- [ ] 上传文件后 `knowledge_file.oss_path` 写入非空的完整 OSS 路径
- [ ] 存量 `oss_path = ""` 的记录有修复脚本或补偿方案说明
- [ ] 单测覆盖 `uploadFile()` 中 OSS 路径赋值逻辑
