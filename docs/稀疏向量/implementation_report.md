# 稀疏向量实现报告

## 1. 实现范围

本次按已冻结的 `technical_design.md` 进入实现阶段，落地 BGE-M3 稀疏向量接入的核心链路：

- 配置层默认开启 `SPARSE_VECTOR_ENABLED`。
- 删除外部 `SPARSE_VECTOR_USE_FP16` 配置入口。
- BGE-M3 推理精度由 `SPARSE_VECTOR_DEVICE` 唯一推导：CPU 为 fp32，CUDA 为 fp16。
- 向量存储阶段把 dense 与 sparse 放入同一 chunk 成功边界。
- Qdrant 使用同一 `chunk_id` 写入 dense vector 与 named sparse vector。
- MySQL 增加并使用独立 sparse 状态字段，作为跨库一致性的事实源。
- 将 `kb_document_chunk` 中原稠密向量生命周期字段从通用命名修正为 `dense_vector_*`，避免与 sparse 状态字段混用。
- 未新增独立的 dense 生成结果字段；`dense_vector_status` 直接承接原 `status` 的完整生命周期枚举。
- `sparse_vector_status` 与 `dense_vector_status` 使用一致的生命周期枚举，成功入库统一表达为 `INDEXED`。

## 2. 主要落点

| 类型 | 文件 |
| :--- | :--- |
| 配置 | `src/config.py`、`.env.example` |
| 稀疏向量模块 | `src/core/sparse_vector/*` |
| 向量存储编排 | `src/core/vector_storage/pipeline.py`、`management_pipeline.py`、`compensation_pipeline.py`、`factory.py` |
| Qdrant | `src/core/qdrant_vector_storage/models.py`、`point_factory.py`、`qdrant_store.py` |
| MySQL 状态 | `src/core/chunk_fact_storage/repository.py`、`src/models/chunk_record.py`、`migrations/versions/0004_20260519_add_sparse_vector_fields.py`、`migrations/versions/0005_20260519_rename_dense_vector_fields.py` |
| 测试 | `tests/unit/test_config_sparse_vector.py`、`tests/unit/core/sparse_vector/*`、`tests/unit/scripts/test_benchmark_bge_m3_sparse.py`、`tests/unit/core/vector_storage/*`、`tests/unit/core/qdrant_vector_storage/*`、`tests/unit/core/chunk_fact_storage/*`、`tests/integration/core/vector_storage/test_dense_sparse_consistency.py` |
| 文档同步 | `docs/guides/configuration.md`、`docs/architecture/vectorization_module.md`、`docs/reference/mysql_schema.md`、`docs/reference/qdrant_schema.md`、`docs/稀疏向量/*` |

## 3. 与技术设计的差异

| 项目 | 结果 |
| :--- | :--- |
| CPU int8 / 量化模型 | 未实现，按冻结方案复用普通 BGE-M3，CPU 使用 fp32 |
| `SPARSE_VECTOR_USE_FP16` | 未保留，外部配置完全移除 |
| ES 事务 | 未接入，符合“ES 不由本模块处理”的边界 |
| 真实 BGE-M3 集成测试 | 保留显式开关，不进入默认测试 |

## 4. 一致性处理

- MySQL 仍是 chunk 事实源。
- `dense_vector_status/error_msg/retry_count/last_retry_at` 承接原稠密向量生命周期与补偿状态。
- `sparse_vector_status/*` 表达稀疏向量生成与写入结果，不与 dense 字段混用。
- dense 与 sparse 的成功态均为 `INDEXED`；文件级向量化成功要求两者均为 `INDEXED`。
- Qdrant 写入成功但 MySQL 回写失败时，不把 chunk 或文件级向量化判定为成功。
- sparse 状态回写会避开 `DELETING` / `DELETED` / `DELETE_FAILED` 等删除保护状态。
- 重试时保持同一 `chunk_id` 幂等覆盖 Qdrant point，避免重复索引。

## 5. 验证结果

已执行：

```bash
.venv\Scripts\python.exe -m py_compile src/core/sparse_vector/encoder.py src/core/sparse_vector/factory.py src/core/sparse_vector/pipeline.py src/core/sparse_vector/deploy_bge_m3.py scripts/benchmark_bge_m3_sparse.py src/core/vector_storage/pipeline.py src/core/chunk_fact_storage/repository.py tests/integration/core/vector_storage/test_dense_sparse_consistency.py tests/unit/scripts/test_benchmark_bge_m3_sparse.py
.venv\Scripts\python.exe -m pytest tests/unit/core/sparse_vector tests/unit/scripts/test_benchmark_bge_m3_sparse.py tests/unit/test_config_sparse_vector.py -q
.venv\Scripts\python.exe -m pytest tests/unit/test_config_sparse_vector.py tests/unit/core/sparse_vector tests/unit/core/vector_storage tests/unit/core/qdrant_vector_storage tests/unit/core/chunk_fact_storage -q
.venv\Scripts\python.exe -m pytest tests/unit -q
.venv\Scripts\python.exe -m pytest tests/integration/core/vector_storage/test_dense_sparse_consistency.py -q
.venv\Scripts\python.exe -m py_compile src\models\chunk_record.py src\core\chunk_fact_storage\models.py src\core\chunk_fact_storage\repository.py src\core\vector_storage\models.py src\core\vector_storage\pipeline.py src\core\vector_storage\management_pipeline.py src\core\vector_storage\compensation_pipeline.py src\core\vector_storage\_transaction.py src\core\vector_storage\repair_policy.py
.venv\Scripts\python.exe -m pytest tests\unit\core\chunk_fact_storage tests\unit\core\vector_storage -q
.venv\Scripts\python.exe -m pytest --run-integration tests\integration\core\vector_storage\test_dense_sparse_consistency.py -q
git diff --check
```

结果：

- 稀疏向量与 benchmark 配置单元测试：`19 passed`
- 目标单元测试：`110 passed`
- 全量单元测试：`325 passed`
- 新增真实环境集成测试：未开启真实环境变量时 `1 skipped`
- 字段修复后针对性单元测试：`78 passed`
- 字段修复后 dense+sparse 一致性集成入口：未开启真实环境变量时 `1 skipped`
- 字段修复后 `py_compile` 与 `git diff --check` 通过
- 文档同步规则：`0 error`，剩余 `2 warning` 来自既有非本需求文件变更

## 6. 遗留事项

- `docs/稀疏向量/brief.md` 已按字段修复同步读时过滤字段名；CPU 推理相关表述已与已冻结的 acceptance 与 technical design 对齐。
- 真实 MySQL + Qdrant + BGE-M3 联合验证需在具备外部依赖和模型文件的环境中显式开启。
