# 解析任务OOM风险治理 实施报告

- **关联设计：** [brief.md](./brief.md) / [acceptance.feature](./acceptance.feature) / [technical_design.md](./technical_design.md)
- **实施日期：** 2026-05-19
- **复杂度：** L3（多模块、多文件、协议破坏式替换）
- **测试结果：** `pytest tests/unit tests/acceptance` 317 passed / 0 failed
- **acceptance.feature** 17 条 Scenario（Outline 展开后 18 条 pytest case）全绿（pytest-bdd 直接加载）

---

## 1. 实施范围实际清单

### 1.1 源代码改动

| 文件 | 动作 | 说明 |
| :--- | :--- | :--- |
| `pyproject.toml` | 修改 | dev 依赖新增 `pytest-bdd>=7.0.0` |
| `src/config.py` | 修改 | 新增 `PARSE_TEMP_DIR`（默认 `/tmp/tolink-rag-parse`） |
| `src/main.py` | 修改 | lifespan 在 `start_parse_consumer` 之前调用 `temp_workspace.ensure_clean_on_startup` |
| `src/services/storage/base.py` | 修改 | 移除 `download_bytes`，新增 `download_to_path(bucket, key, dst: Path)` |
| `src/services/storage/minio_storage.py` | 修改 | 实现 `download_to_path`：`open(dst, "wb") + boto3 download_fileobj` 分块写盘 |
| `src/services/storage/oss_storage.py` | 修改 | 协议对齐，`download_to_path` 保留 `NotImplementedError` 占位 |
| `src/core/pipeline/parse_task/temp_workspace.py` | **新增** | `ensure_clean_on_startup` / `create_temp_file` / `safe_unlink` 三个函数 |
| `src/core/pipeline/parse_task/source.py` | 修改 | `download(payload) -> bytes` → `download_to_path(payload, dst)` |
| `src/core/pipeline/parse_task/pipeline.py` | 修改 | `_run` 重写源文件段：临时文件创建/早删/finally 兜底 + ENOSPC 分类 + 观测日志；`_parse_file` 改为 `source_path: Path \| None` |
| `src/core/pipeline/parse_task/error_codes.py` | 修改 | 新增 `ParseFailureCode.TEMP_DISK_FULL` 与中文文案 |
| `src/services/parse_task_service.py` | 修改 | `aprocess/process_sync/_parse_markdown` 入参 `file_stream: bytes` → `source_path: Path \| None` |
| `src/core/parser/base.py` | 修改 | `IFileParser.parse(source: Path \| None)`；`BaseParser.validate_stream` → `validate_source` |
| `src/core/parser/providers/word_parser.py` | 修改 | `docx.Document(str(source))`，移除 `BytesIO` |
| `src/core/parser/providers/html_parser.py` | 修改 | `Path(source).read_text(...)`，移除 bytes.decode |
| `src/core/parser/providers/pdf_parser.py` | 修改 | `can_skip_local_pdf = source is None`；`fitz.open(filename=str(source))` |
| `src/core/parser/pdf/base.py` | 修改 | 抽象 `parse` 签名同步改 path 入参 |
| `src/core/parser/pdf/service.py` | 修改 | `PdfParserService.parse` / `_prepare_image_uploads` / `_upload_images` 接受 path；`fitz.open(filename=...)` |
| `src/core/parser/pdf/backends/naive_backend.py` | 修改 | `fitz.open(filename=)`、`pymupdf4llm.to_markdown(str(source))`；删除 `tempfile.NamedTemporaryFile` 二次落盘 |
| `src/core/parser/pdf/backends/opendataloader_backend.py` | 修改 | 直接传 `source` 给 `convert(input_path=[str(source)])`；删除 `pdf_path.write_bytes` |
| `src/core/parser/pdf/backends/mineru_backend.py` | 修改 | 签名对齐，行为不变（仅依赖 `source_file_url`） |
| `src/api/routes/parse.py` | 修改 | `/extract_sync` 把 multipart upload 分块写入 `PARSE_TEMP_DIR` 临时文件再喂给 parser（finally 清理） |
| `src/utils/file_downloader.py` | **删除** | 孤立兼容包装器，依赖 `download_bytes`，无任何上游调用 |
| `.env.example` | 修改 | 新增 `PARSE_TEMP_DIR` 示例与注释 |

### 1.2 测试改动

| 文件 | 动作 |
| :--- | :--- |
| `tests/acceptance/__init__.py` | 新增 |
| `tests/acceptance/conftest.py` | 新增——共享 fixture（`state` / `fake_storage` / `payload_factory` / `parse_service_stub` / `pipeline_factory`）+ star-import 各 step 模块 |
| `tests/acceptance/test_parse_task_oom_governance.py` | 新增——一行 `scenarios(str(_FEATURE))` 加载 `docs/解析任务OOM风险治理/acceptance.feature` |
| `tests/acceptance/steps/__init__.py` | 新增 |
| `tests/acceptance/steps/background_steps.py` | 新增 |
| `tests/acceptance/steps/storage_steps.py` | 新增 |
| `tests/acceptance/steps/pipeline_steps.py` | 新增 |
| `tests/acceptance/steps/parser_steps.py` | 新增 |
| `tests/acceptance/steps/temp_workspace_steps.py` | 新增 |
| `tests/acceptance/steps/logging_steps.py` | 新增 |
| `tests/unit/core/pipeline/parse_task/__init__.py` | 新增 |
| `tests/unit/core/pipeline/parse_task/test_temp_workspace_unit.py` | 新增——`safe_unlink` 幂等、命名规则、子目录保留等 8 个边界单测 |
| `tests/unit/core/pipeline/test_parse_task_pipeline.py` | 修改——`download_bytes` 系列断言替换为 `download_to_path`；MinerU 旁路断言 `args[0] is None` |
| `tests/unit/core/parser/test_pdf_backends.py` | 修改——MinerU 旁路用例改用 `source=None` 而非 `b""` |
| `tests/integration/core/mq/test_kafka_parse_task_pipeline_integration.py` | 修改——同上批量替换 |
| `tests/integration/services/test_minio_pdf_parse_integration.py` | 重写——使用 `download_to_path` 流式拉取 + finally 清理临时文件 |

### 1.3 文档同步

| 文件 | 动作 |
| :--- | :--- |
| `docs/reference/error_codes.md` | 新增 `TEMP_DISK_FULL` 行 |
| `docs/architecture/object_storage_module.md` | 接口章节由 `download_bytes` 改为 `download_to_path`；解析链路调用图同步 |
| `docs/architecture/parse_task_pipeline_module.md` | 模块树新增 `temp_workspace.py`；阶段表新增临时文件生命周期描述与 ENOSPC→TEMP_DISK_FULL 分类 |
| `docs/architecture/file_parser_module.md` | parser 协议说明改为 `parse(source: Path \| None)` |
| `docs/architecture/project_structure.md` | 移除已删除的 `src/utils/file_downloader.py` 引用 |
| `docs/guides/configuration.md` | 配置分组速览新增"解析临时目录"；关键开关表新增 `PARSE_TEMP_DIR` 默认值与运维提示 |

---

## 2. 与技术方案的差异

### 2.1 显著差异

#### 2.1.1 `src/api/routes/parse.py::extract_sync` 同步改造（计划外）

**TD 描述**：第 3.1 节改动文件树未列出该路由文件。

**实际处理**：`/extract_sync` 端点接收 multipart upload，旧实现走 `file = await file.read()` 拿 bytes 直接传 `ParseTaskService.aprocess`。由于本次把 `aprocess` 入参改为 `Path | None`，这个 HTTP 入口会编译失败。

**实施方案**：在路由内将 multipart 流分块写入 `PARSE_TEMP_DIR/parse-{filename}-{rand}.tmp`（1MB chunk），喂给 `aprocess(Path)`，`finally` 兜底 `safe_unlink`。这样 HTTP 联调端点与 MQ 主流程共享同一份临时文件治理约束。

**为什么没有触发"扩范围确认"**：这属于"协议破坏式替换的必然链式修复"，TD §12 风险表中"老 `download_bytes` / `parse(bytes)` 遗留点"已显式纳入"改造时 grep 收敛"范围，归在已知必修项。

#### 2.1.2 `src/utils/file_downloader.py` 被删除（计划外）

**TD 描述**：未提及。

**实际处理**：grep 发现是孤立包装器，全仓无任何上游引用（包括 `docs/architecture/project_structure.md` 也只是文件清单中提及）。保留它会让 `download_bytes` 在源码里"活下来"，构成 TD §12 提及的"静默回退"隐患——直接删除并同步 `project_structure.md`。

#### 2.1.3 `BasePdfBackend` 抽象签名也被改动（计划外细化）

**TD 描述**：列出三个具体 backend 的修改，没单独列 `src/core/parser/pdf/base.py`。

**实际处理**：Python 抽象基类如果接口签名不对齐，子类实现签名不一致会触发静态/运行时混乱。同步把 `BasePdfBackend.parse(file_stream, options)` 改为 `parse(source: Path | None, options)`。

### 2.2 微调差异

#### 2.2.1 `_handle_execution_failure` 没有抽出独立帮助函数

TD §7.2.6 伪码示意"分类失败统一走 `_handle_execution_failure`"，已是现成函数，本次直接复用，未做改动。

#### 2.2.2 pytest-bdd 中文 Gherkin 关键字处理

TD §10.1 说 "acceptance.feature 头部已声明 `# language: zh-CN`"。实际跑 pytest-bdd 8.1.0 时这条指令会让 parser 期待中文关键字（假如/当/那么），与文件中实际使用的 English `Given/When/Then` 冲突。

**处理**：移除 `# language: zh-CN` 指令，改用默认 English 关键字 + 中文 step 文本的"混合 Gherkin"写法。已在 acceptance.feature 顶部注释中说明这一选择。technical_design.md 的描述与实际行为略有偏差但语义无损——本报告留作记录，未回写 TD。

#### 2.2.3 acceptance fixture 中加入 0.002s 解析延迟

TD §10 没有要求测试桩对耗时做注入。实际：`parse_ms > 0` 这条 observability 契约要求 `time.monotonic()` 差值 > 0，零耗时桩会让契约判错。conftest 的 `_aprocess` 桩注入 `await asyncio.sleep(0.002)` 让 parse_ms 计数 ≥ 2ms。

---

## 3. 关键代码落点

### 3.1 `temp_workspace`

```text
src/core/pipeline/parse_task/temp_workspace.py
  - ensure_clean_on_startup(temp_dir)  # lifespan 启动时清空兜底
  - create_temp_file(task_id, temp_dir) -> Path  # 命名: parse-{task_id}-{hex8}.tmp
  - safe_unlink(path | None)  # 幂等删除
```

### 3.2 ParseTaskPipeline._run 关键段

```text
src/core/pipeline/parse_task/pipeline.py:140-225
  - source_path: Path | None = None
  - 非旁路：create_temp_file → download_to_path（含 ENOSPC 分类）→ 观测日志
  - _parse_file(source_path) → 观测日志 → safe_unlink + source_path = None（早删）
  - finally: safe_unlink(source_path)（异常路径兜底）
```

### 3.3 协议破坏式替换的边界

```text
IFileParser.parse(source: Path | None) -> str
  ↓
WordParser / HtmlParser / PdfParser
  ↓
PdfParserService.parse(source, options)
  ↓
BasePdfBackend.parse(source, options)
  ↓
naive_backend / opendataloader_backend / mineru_backend
```

旁路语义：`source is None`（取代旧的 `file_stream == b""`）。

---

## 4. 测试覆盖

### 4.1 pytest-bdd acceptance 层（新增）

```bash
.venv/bin/pytest tests/acceptance --collect-only -q  # 18 tests collected
.venv/bin/pytest tests/acceptance -v                  # 18 passed
```

覆盖的 17 条 Scenario（含 1 个 Scenario Outline 展开为 4 条 examples），pytest 收集到的 case 总数 18：

| 分类 | 数量 | 通过情况 |
| :--- | :---: | :---: |
| 主流程（含 MinerU 旁路 / 四类非旁路 Outline / 早删） | 6 | ✅ |
| 异常路径（404 / ENOSPC / 解析失败 / 上传失败 finally） | 4 | ✅ |
| 启动清理（残留清空 / 缺目录创建） | 2 | ✅ |
| 内存治理约束（download_bytes 调用次数 == 0 / parser 拒绝 bytes） | 2 | ✅ |
| 观测日志（下载 / 解析两行字段断言） | 2 | ✅ |
| 存储驱动（MinIO download_fileobj / OSS 占位） | 2 | ✅ |

### 4.2 unit + acceptance 全量

```bash
.venv/bin/pytest tests/unit tests/acceptance -q
# 317 passed in 1.39s
```

含：
- 新增 8 个 `test_temp_workspace_unit.py` 边界用例
- 原有 ~290 个单测全部通过（已批量改造为新 API）
- 18 个 pytest-bdd acceptance 用例

### 4.3 未运行

- `tests/integration/**`：默认不跑（仓库约定 `--run-integration` 才收集），已按新 API 同步代码但本次未触发真实环境联调。
- 集成测试 `test_minio_pdf_parse_integration.py` 已重写，但需要真实 MinIO 配置才能运行。

---

## 5. 遗留风险与后续事项

| 项 | 状态 | 说明 |
| :--- | :--- | :--- |
| OSS 驱动 `download_to_path` 实际 SDK 接入 | 占位 | 与 brief / TD 一致：本次只对齐协议，留待生产切换 OSS 时独立改造 |
| Java 端识别 `TEMP_DISK_FULL` | 待报备 | PR 描述需提及；Java 端无需代码改动，但建议同步登记错误码字典 |
| `PARSE_TEMP_DIR` 容量监控 | 未做 | brief 已明确"不预设最小容量"；运维通过系统盘水位告警兜底 |
| 真实集成环境联调 | 未做 | 默认 `--run-integration` 关闭；建议合入主干前手工跑一次大 docx 真实下载链路 |
| 扩消费者后并发未受控 | 已知 | brief / TD §4 风险表已列；本次显式"不做"，扩消费者前需补"并发闸 / worker 内存监控"独立改造项 |
| MinerU URL 旁路的 PDF 仍然走云端 API 上传 PDF | 不变 | MinerU backend 内部依赖 `source_file_url`，与本次治理无关；保持原状 |

---

## 6. 回滚方案

代码回滚到合入前 commit 即可。本次：

- 无数据库 schema 改动
- 无 MQ 契约改动
- 仅新增一个 `TEMP_DISK_FULL` 错误码（Java 端"未知 code 透传到运营后台"逻辑兜底）
- 配置 `PARSE_TEMP_DIR` 有默认值，旧部署无需修改 `.env`

回滚后 Java 端不会再收到 `failure_reason=TEMP_DISK_FULL:...`，历史失败任务记录保留。

---

## 7. 自检清单

- [x] §3.1 改动文件目录树已与实际 diff 比对，确认 §2.1 列出的所有差异
- [x] §7.1 方法级变更总表所有方法均已落地（`temp_workspace.*`、`_run`、`_parse_file`、协议层、各 backend）
- [x] §9 异常分类与现有错误码体系无冲突，新增 `TEMP_DISK_FULL` 与 `SOURCE_FILE_NOT_FOUND` 互斥
- [x] acceptance.feature 17 条 Scenario（Outline 展开后 18 条 pytest case）全部通过 pytest-bdd
- [x] 全量 `pytest tests/unit tests/acceptance -q` 317 passed / 0 failed
- [x] doc-sync ❌ error 级文件全部更新：`parse_task_pipeline_module.md` / `error_codes.md`
- [x] doc-sync ⚠️ warning 级文件全部更新：`object_storage_module.md` / `file_parser_module.md` / `configuration.md` / `project_structure.md`
- [x] `.env.example` 与 `src/config.py` 同步
