# 模块开发文档目录说明

本目录用于沉淀模块级研发文档，按“模块目录 + 期次目录”的方式组织。

## 目录规范

- 模块目录：`docs/module-development-files/<module-name>/`
- 期次目录：`docs/module-development-files/<module-name>/<phase>/`

当前仓库统一采用以下约定：

- `feature_info.md`：模块当前期次的摘要索引
- `requirement.md`：需求分析文档
- `technical_design.md`：技术设计文档

## 使用规则

- 每次新增模块需求时，先创建模块目录
- 如果需求不拆期，仍使用 `一期/` 作为当前唯一交付期次目录
- `feature_info.md` 和 `requirement.md` 需要保持同步
- 需求分析完成后状态应停留在“需求待审核”
