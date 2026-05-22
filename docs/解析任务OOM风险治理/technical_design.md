# 解析任务OOM风险治理 技术设计

- **文档状态：** 技术方案待审核
- **项目名称：** toLink-Rag
- **业务域：** 文档解析流水线
- **需求名称：** 解析任务OOM风险治理
- **业务输入：** [brief.md](./brief.md)
- **验收输入：** [acceptance.feature](./acceptance.feature)
- **输出文件：** [technical_design.md](./technical_design.md)
- **最后更新时间：** 2026-05-19

---

## 1. 文档修订记录

| 版本号 | 修改日期 | 修改内容简述 | 来源/提出人 | 审核状态 |
| :--- | :--- | :--- | :--- | :--- |
| v1.0 | 2026-05-19 | 初始技术设计创建 | brief.md + acceptance.feature | 待审核 |

---

## 2. 输入依据与设计目标

### 2.1 输入依据映射

| 输入来源 | 关键结论 | 技术设计承接方式 |
| :--- | :--- | :--- |
| `brief.md` §1 | 治理范围限定为非 MinerU 旁路（PDF 非 MinerU 后端 / DOCX / DOC / HTML） | 改造点集中在 `ParseSourceIO.download` → `download_to_path` 与 parser 协议；MinerU URL 旁路保持原状 |
| `brief.md` §2.3 | 临时文件早删（拿到 markdown 即删，finally 兜底） | `_run` 内分两段清理：成功路径 `os.unlink` 立即删；外层 `try/finally` 二次兜底 |
| `brief.md` §3.2 / §3.4 | 存储 / parser 协议破坏式替换，MinIO + OSS 同改 | `BaseObjectStorage` 移除 `download_bytes`、新增 `download_to_path`；`IFileParser.parse(bytes)` → `parse(Path \| None)` |
| `brief.md` §3.6 / §3.7 | 新增 `PARSE_TEMP_DIR` 配置 + `TEMP_DISK_FULL` 错误码 | `Settings.PARSE_TEMP_DIR`、`ParseFailureCode.TEMP_DISK_FULL`、`FAILURE_REASON_TEXT` 同步 |
| `brief.md` §3.8 | 结构化观测日志（file_size_mb / download_ms / parse_ms / markdown_chars） | `_run` 在下载、解析两个边界打 loguru 结构化日志 |
| `acceptance.feature` 17 个 Scenario | 主流程 5 / 异常 4 / 启动清理 2 / 内存治理 2 / 观测日志 2 / 存储驱动 2 | 见 §10 测试映射，每条 Scenario 对应到具体方法与测试断言 |

### 2.2 技术目标

- 把"非旁路路径"的单任务峰值内存从 `2–3 × 文件大小` 降至 parser 内部 buffer 量级（mmap / 流式 IO）。
- 不引入任何"bytes 兼容路径"，杜绝后续静默回退；老 `download_bytes` 与 `parse(bytes)` 一次性下线。
- 所有源文件临时落盘集中到独立目录 `PARSE_TEMP_DIR`，worker 启动时清空兜底进程异常残留。
- MinerU URL 旁路语义不变：`source_path = None`（取代旧的 `file_stream = b""`），分支判定逻辑等价。
- 新增 `TEMP_DISK_FULL` 错误码，与 `SOURCE_FILE_NOT_FOUND` 区分定位。

### 2.3 显式不做（来自 brief.md §1）

- 不引入 worker 级并发信号量 / 限流。
- 不改 MQ 消息契约、`document_parsed_log` 状态机、对外错误码语义（仅新增一条 `TEMP_DISK_FULL`）。
- markdown 上传侧（`upload_bytes`）保持不变（KB 级，无内存压力）。
- PDF backends 业务逻辑不变，仅替换"如何读到文件内容"。

---

## 3. 改动范围

### 3.1 改动文件目录树

```text
toLink-Rag/
├── pyproject.toml                                             # [修改] dev 可选依赖新增 pytest-bdd>=7.0.0
├── src/
│   ├── config.py                                              # [修改] 新增 PARSE_TEMP_DIR 配置项
│   ├── main.py                                                # [修改] lifespan 启动时调用 PARSE_TEMP_DIR 清理钩子
│   ├── services/
│   │   └── storage/
│   │       ├── base.py                                        # [修改] 协议: 移除 download_bytes，新增 download_to_path
│   │       ├── minio_storage.py                               # [修改] 实现 download_to_path (boto3 download_fileobj)
│   │       └── oss_storage.py                                 # [修改] 实现 download_to_path (oss2 get_object_to_file 占位)
│   └── core/
│       ├── parser/
│       │   ├── base.py                                        # [修改] IFileParser.parse 入参 bytes→Path|None; validate_stream→validate_source
│       │   ├── providers/
│       │   │   ├── word_parser.py                             # [修改] docx.Document(path); 删除 BytesIO 引用
│       │   │   ├── html_parser.py                             # [修改] 改为 open(path,'rb').read().decode
│       │   │   └── pdf_parser.py                              # [修改] parse(Path|None); MinerU 旁路判定改为 source is None
│       │   └── pdf/
│       │       ├── service.py                                 # [修改] PdfParserService.parse(Path|None,options); fitz.open(filename=)
│       │       └── backends/
│       │           ├── naive_backend.py                       # [修改] 直接 fitz.open(filename=path), pymupdf4llm.to_markdown(path)
│       │           ├── opendataloader_backend.py              # [修改] 跳过 write_bytes，直接传 path 给 convert
│       │           └── mineru_backend.py                      # [修改] 接口签名对齐 (实际不读 file 内容，依然只用 source_file_url)
│       └── pipeline/
│           └── parse_task/
│               ├── __init__.py                                # [不改]
│               ├── source.py                                  # [修改] download→download_to_path; 移除 bytes 返回
│               ├── pipeline.py                                # [修改] 临时文件生命周期 + 早删 + finally 兜底 + 观测日志
│               ├── error_codes.py                             # [修改] 新增 ParseFailureCode.TEMP_DISK_FULL + 中文文案
│               └── temp_workspace.py                          # [新增] PARSE_TEMP_DIR 启动清理 + 临时文件工厂
├── docs/
│   ├── reference/
│   │   └── error_codes.md                                     # [修改] 同步 TEMP_DISK_FULL（doc-sync ⚠️ warning）
│   ├── architecture/
│   │   ├── object_storage_module.md                           # [修改] 接口章节: 下载侧改为 download_to_path
│   │   ├── parse_task_pipeline_module.md                      # [修改] 源文件 IO 段落 + 临时文件生命周期（doc-sync ❌ error）
│   │   └── file_parser_module.md                              # [修改] parser 协议签名说明
│   └── guides/
│       └── configuration.md                                   # [修改] 新增 PARSE_TEMP_DIR 配置项说明
├── .env.example                                               # [修改] 新增 PARSE_TEMP_DIR 示例
└── tests/
    ├── acceptance/                                            # [测试新增] 本次新增的 pytest-bdd 验收层
    │   ├── __init__.py                                        # [测试新增]
    │   ├── conftest.py                                        # [测试新增] 共享 fixture：fake storage / payload factory / 捕获日志 / 临时目录
    │   ├── test_parse_task_oom_governance.py                  # [测试新增] scenarios("../../docs/解析任务OOM风险治理/acceptance.feature")
    │   └── steps/
    │       ├── __init__.py                                    # [测试新增]
    │       ├── background_steps.py                            # [测试新增] Background 与公共 Given
    │       ├── storage_steps.py                               # [测试新增] download_to_path / MinIO / OSS 驱动断言
    │       ├── pipeline_steps.py                              # [测试新增] _run 主流程 + 异常路径 + 临时文件早删
    │       ├── parser_steps.py                                # [测试新增] parser 协议入参为 Path 断言
    │       ├── temp_workspace_steps.py                        # [测试新增] 启动清理两条
    │       └── logging_steps.py                               # [测试新增] 观测日志字段断言
    ├── unit/
    │   └── core/pipeline/parse_task/test_temp_workspace_unit.py  # [测试新增] temp_workspace 边界单测（safe_unlink 幂等等内部行为）
    └── integration/
        └── services/test_minio_pdf_parse_integration.py       # [测试修改] 已有用例同步切换到 download_to_path API
```

### 3.2 文件级改动说明

| 文件 | 动作 | 改动目的 | 是否必须 |
| :--- | :--- | :--- | :--- |
| `src/services/storage/base.py` | 修改 | 协议层移除 bytes 下载、新增 path 下载抽象 | 是 |
| `src/services/storage/minio_storage.py` / `oss_storage.py` | 修改 | 两家驱动同步实现 path 下载（OSS 当前为占位，本次落地） | 是 |
| `src/core/pipeline/parse_task/source.py` | 修改 | 流水线对存储的唯一入口 path 化 | 是 |
| `src/core/pipeline/parse_task/pipeline.py` | 修改 | 临时文件生命周期 + 错误分类 + 观测日志主战场 | 是 |
| `src/core/pipeline/parse_task/temp_workspace.py` | 新增 | 把"目录确保 / 启动清空 / 临时文件创建"集中到一个模块，避免 pipeline 直接散写 | 是 |
| `src/core/pipeline/parse_task/error_codes.py` | 修改 | 新增 `TEMP_DISK_FULL`（错误码契约同步） | 是 |
| `src/core/parser/base.py` 与三个 provider | 修改 | 协议破坏式替换，斩断 bytes 残留路径 | 是 |
| `src/core/parser/pdf/service.py` 与 3 个 backends | 修改 | 把"读文件"下沉到 mmap / 流式 API；不改业务逻辑 | 是 |
| `src/main.py` | 修改 | lifespan 启动钩子调用临时目录清理（acceptance: 启动清理两条） | 是 |
| `src/config.py` / `.env.example` / `docs/guides/configuration.md` | 修改 | 新增 `PARSE_TEMP_DIR` 配置 | 是 |
| `docs/reference/error_codes.md` | 修改 | 新增错误码同步（doc-sync 强制） | 是 |
| `docs/architecture/parse_task_pipeline_module.md` | 修改 | 解析流水线状态机文档（doc-sync ❌ error 级） | 是 |
| `docs/architecture/object_storage_module.md` / `file_parser_module.md` | 修改 | 接口协议同步 | 是 |
| `pyproject.toml` | 修改 | dev 依赖新增 `pytest-bdd>=7.0.0`，让 `acceptance.feature` 升级为 pytest 直接加载的可执行契约 | 是 |
| `tests/acceptance/**` 新增 | 测试 | pytest-bdd 加载 `acceptance.feature`，每条 Scenario 走 step 实现 | 是 |
| `tests/unit/core/pipeline/parse_task/test_temp_workspace_unit.py` | 测试 | `safe_unlink` 幂等等无法从业务 Scenario 自然表达的内部边界 | 是 |
| `tests/integration/...` | 修改 | 现有集成用例同步切换 API | 是 |
| `migrations/`、`scripts/db/init.sql`、`src/models/`、MQ 消息契约 | 不改 | 本次不涉及 schema / 消息契约 | — |

---

## 4. 当前系统分析

| 类型 | 文件/类/方法 | 当前行为 | 问题或复用点 |
| :--- | :--- | :--- | :--- |
| 协议 | `BaseObjectStorage.download_bytes` | 抽象方法返回完整对象 bytes | 不可避免地内存驻留，需替换 |
| 实现 | `MinioStorage.download_bytes` | `response["Body"].read()` 一次性读完 | 改为 `client.download_fileobj(Bucket, Key, Fileobj)` |
| 实现 | `OssStorage.download_bytes` | `NotImplementedError` 占位 | 顺带把 path 版本一起落地 |
| 协作者 | `ParseSourceIO.download` | 透传 `download_bytes` 返回 bytes | 改为 `download_to_path(dst)` |
| 编排 | `ParseTaskPipeline._run` (pipeline.py:140-183) | `file_bytes = await asyncio.to_thread(self._source_io.download, payload)`；空 bytes (`b""`) 表示 MinerU 旁路 | 替换为临时文件 path；空表达改为 `source_path = None` |
| 编排 | `ParseTaskPipeline._parse_file` | `parser.parse(file_stream: bytes)` | 入参改为 `source_path: Path \| None` |
| 服务 | `ParseTaskService.aprocess` | `file_stream: bytes` | 改为 `source_path: Path \| None` |
| 协议 | `IFileParser.parse(file_stream: bytes)` | bytes 输入 | 破坏式替换为 `parse(source: Path \| None)` |
| 实现 | `WordParser.parse` | `docx.Document(BytesIO(file_stream))` | `docx.Document(path)`（python-docx 原生支持） |
| 实现 | `HtmlParser.parse` | `file_stream.decode('utf-8', errors='ignore')` | `Path(source).read_bytes().decode(...)` 或 `open(source).read()` |
| 实现 | `PdfParser.parse` | `can_skip_local_pdf = mineru + URL + not file_stream` | 旁路判定改为 `source is None` |
| 服务 | `PdfParserService.parse` | `fitz.open(stream=file_stream)` + 把 bytes 交给后端 | `fitz.open(filename=str(path))` + 后端接 path |
| 后端 | `NaiveBackend.parse` | `fitz.open(stream=)` + `pymupdf4llm.to_markdown(tempfile)` | 直接 `fitz.open(filename=)`、`pymupdf4llm.to_markdown(str(path))` |
| 后端 | `OpenDataLoaderBackend.parse` | 写 bytes 到 temp_dir/document.pdf | 直接传 path 给 `opendataloader_pdf.convert` |
| 后端 | `MineruBackend.parse` | 不依赖 `file_stream`（只用 `source_file_url`） | 签名对齐即可 |
| 错误码 | `ParseFailureCode` 枚举 | 已含 `SOURCE_FILE_NOT_FOUND` / `PARSE_ENGINE_FAILED` 等 | 追加 `TEMP_DISK_FULL` |
| 启动 | `src/main.py::lifespan` | 当前无临时目录治理 | 注入"启动清空 PARSE_TEMP_DIR"钩子 |

---

## 5. 总体方案设计

### 5.1 总体流程（治理后）

```mermaid
flowchart TD
    A["MQ 回调"] --> B["ParseTaskPipeline._run"]
    B --> C{"should_skip_source_download?"}
    C -->|是 (PDF+MinerU)| D["source_path = None"]
    C -->|否| E["temp_workspace.create_temp_file()"]
    E --> F["download_to_path(payload, tmp)"]
    F -.->|OSError ENOSPC| FE["TEMP_DISK_FULL → mark_failed"]
    F -.->|对象存储 404| FN["SOURCE_FILE_NOT_FOUND → mark_failed"]
    F --> G["log: source downloaded (file_size_mb, download_ms)"]
    D --> H["_parse_file(source_path)"]
    G --> H
    H --> I["log: parse completed (parse_ms, markdown_chars)"]
    I --> J["os.unlink(tmp) — 早删"]
    J --> K["upload_markdown → 后续 chunk/向量/ES"]
    H -.->|异常| HE["PARSE_ENGINE_FAILED + finally unlink"]
    K --> END["终态 SUCCESS"]
    FE --> END
    FN --> END
    HE --> END
```

### 5.2 模块边界

| 模块 | 职责 | 本次是否改动 |
| :--- | :--- | :--- |
| `services/storage` | 对象存储抽象与驱动 | 是（接口 + MinIO + OSS） |
| `core/pipeline/parse_task/source` | pipeline 到存储的协作者 | 是 |
| `core/pipeline/parse_task/pipeline` | 流水线主编排 | 是（核心） |
| `core/pipeline/parse_task/temp_workspace` | 临时目录治理 | 新增 |
| `core/pipeline/parse_task/error_codes` | 失败码字典 | 是（新增 1 条） |
| `core/parser` | parser 协议 + provider + PDF backends | 是（签名层） |
| `core/parser/markdown_parser` / 分块 / 向量化 / ES | markdown 之后的链路 | 否 |
| `core/mq/consumers/parse_task_consumer` | MQ 回调 | 否 |
| `core/mq/messages/*` 与 ORM 模型 | 消息契约 / 数据模型 | 否 |
| `src/main.py::lifespan` | 应用生命周期 | 是（仅新增清理钩子） |

---

## 6. API、消息与数据设计

### 6.1 API 设计

无 HTTP API 变更。

### 6.2 MQ 消息设计

无 MQ 消息契约变更。`parse_result` 通知体内 `failure_reason` 字符串可能新增以 `TEMP_DISK_FULL:` 开头的值，Java 端按现有"未识别 code 透传到运营后台"逻辑兜底；新增错误码需在 PR 描述中明示报备 Java 端，但不需要 Java 端代码改动。

### 6.3 数据与存储设计

#### 6.3.1 临时文件命名

- 由 `temp_workspace.create_temp_file(task_id: str) -> Path` 集中分配。
- 命名规则：`{PARSE_TEMP_DIR}/parse-{task_id}-{uuid4().hex[:8]}.tmp`。
  - 含 `task_id` 便于异常时定位归属。
  - 拼接 8 位随机 hex 兜底重投 / 同 task_id 并发的极端情况，避免文件名碰撞。
- 文件权限沿用 `tempfile.NamedTemporaryFile(delete=False)` 默认行为（0o600）。

#### 6.3.2 PARSE_TEMP_DIR 配置

| 字段 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `PARSE_TEMP_DIR` | str | `/tmp/tolink-rag-parse` | 解析源文件临时落盘目录；worker 启动时清空。不预设最小容量，沿用系统盘大小。 |

#### 6.3.3 错误码新增

```python
# src/core/pipeline/parse_task/error_codes.py
TEMP_DISK_FULL = "TEMP_DISK_FULL"

FAILURE_REASON_TEXT[ParseFailureCode.TEMP_DISK_FULL] = "服务器临时磁盘空间不足，请联系运维"
```

`docs/reference/error_codes.md` 同步追加一行（doc-sync ⚠️ warning，但本次属于业务契约扩展，必须同步）。

---

## 7. 方法级实现方案

### 7.1 方法级变更总表

| 文件 | 类/对象 | 方法/成员 | 动作 | 入参变化 | 返回变化 | 改动目的 | 对应 Scenario |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `services/storage/base.py` | `BaseObjectStorage` | `download_bytes` | 删除 | — | — | 杜绝 bytes 静默回退 | 非旁路路径不再调用全量 bytes 下载接口 |
| `services/storage/base.py` | `BaseObjectStorage` | `download_to_path` | 新增 | `(bucket, object_key, dst: Path) -> None` | None | 流式落盘统一抽象 | MinIO 驱动 / OSS 驱动 两条 |
| `services/storage/minio_storage.py` | `MinioStorage` | `download_bytes` | 删除 | — | — | 同上 | — |
| `services/storage/minio_storage.py` | `MinioStorage` | `download_to_path` | 新增 | 同抽象 | None | boto3 `download_fileobj` 分块写入 | MinIO 驱动实现 |
| `services/storage/oss_storage.py` | `OssStorage` | `download_to_path` | 新增 | 同抽象 | None | oss2 `bucket.get_object_to_file`（保留 NotImplemented 兜底直至实际接入） | OSS 驱动实现 |
| `core/pipeline/parse_task/source.py` | `ParseSourceIO` | `download` | 删除 | — | — | 移除 bytes 返回路径 | 非旁路不再调用全量 bytes 下载 |
| `core/pipeline/parse_task/source.py` | `ParseSourceIO` | `download_to_path` | 新增 | `(payload, dst: Path) -> None` | None | 透传给 storage | 非旁路四类文件类型流式下载 |
| `core/pipeline/parse_task/source.py` | `ParseSourceIO` | `upload_markdown` / `build_source_file_url` / `should_skip_source_download` | 不改 | — | — | — | MinerU 跳过下载 / markdown 上传失败 finally 不重复删 |
| `core/pipeline/parse_task/temp_workspace.py` | `TempWorkspace`（模块函数 + 单例守卫） | `ensure_clean_on_startup()` | 新增 | `(path: Path) -> None` | None | 启动时 mkdir + 清空内部文件 | worker 启动时清空 / 不存在则创建 |
| 同上 | — | `create_temp_file(task_id) -> Path` | 新增 | `task_id: str` | `Path` | 集中分配命名 | 非旁路四类文件类型流式下载（参数化） |
| 同上 | — | `safe_unlink(path)` | 新增 | `path: Path \| None` | None | 幂等删除（不存在不抛错） | markdown 上传失败 finally 不重复删 |
| `core/pipeline/parse_task/pipeline.py` | `ParseTaskPipeline` | `_run` | 修改 | — | — | 下载/解析/清理生命周期 + 错误分类 + 观测日志 | 主流程 4 条 / 异常 4 条 / 观测日志 2 条 |
| `core/pipeline/parse_task/pipeline.py` | `ParseTaskPipeline` | `_parse_file` | 修改 | `file_bytes: bytes` → `source_path: Path \| None` | dict（不变） | 透传 path 到 service | 非旁路四类文件类型流式下载 / PDF + MinerU 跳过下载 |
| `core/pipeline/parse_task/error_codes.py` | `ParseFailureCode` | `TEMP_DISK_FULL` | 新增 | — | — | 区分临时盘满与对象存储 404 | 临时盘写满触发新错误码 TEMP_DISK_FULL |
| `core/parser/base.py` | `IFileParser` | `parse` | 修改 | `file_stream: bytes` → `source: Path \| None` | `str` | 协议破坏式替换 | parser 协议入参为 Path |
| `core/parser/base.py` | `BaseParser` | `validate_stream` | 重命名→`validate_source` | `source: Path` | `bool` | 校验文件存在 + 非空 | parser 协议入参为 Path |
| `core/parser/providers/word_parser.py` | `WordParser` | `parse` | 修改 | 同协议 | str | `docx.Document(source)` | 非旁路四类文件类型流式下载 (docx, doc) |
| `core/parser/providers/html_parser.py` | `HtmlParser` | `parse` | 修改 | 同协议 | str | 直接读 path | 非旁路四类文件类型流式下载 (html) |
| `core/parser/providers/pdf_parser.py` | `PdfParser` | `parse` | 修改 | 同协议 | str | `can_skip_local_pdf = source is None`；`fitz.open(filename=)` | PDF + MinerU 跳过下载 / 非旁路 (pdf+docling) |
| `core/parser/pdf/service.py` | `PdfParserService` | `parse` | 修改 | `file_stream: bytes` → `source: Path \| None` | tuple 不变 | 把 path 透传到 backends | 同上 |
| `core/parser/pdf/service.py` | `PdfParserService` | `_prepare_image_uploads` / `_upload_images` | 修改 | bytes→Path\|None | 不变 | `fitz.open(filename=)` | 同上 |
| `core/parser/pdf/backends/naive_backend.py` | `NaiveBackend` | `parse` | 修改 | bytes→Path | tuple 不变 | `fitz.open(filename=)` + `pymupdf4llm.to_markdown(str(path))` | 非旁路 pdf+docling 暂未覆盖 naive；通过测试同步保证签名一致 |
| `core/parser/pdf/backends/opendataloader_backend.py` | `OpenDataLoaderBackend` | `parse` | 修改 | bytes→Path | tuple 不变 | 直接传 path 给 `convert(input_path=[str(path)])`，跳过 write_bytes | 非旁路 pdf (docling/opendataloader) |
| `core/parser/pdf/backends/mineru_backend.py` | `MineruBackend` | `parse` | 修改 | bytes→Path\|None | tuple 不变 | 仅签名对齐，逻辑不变（实际只用 `source_file_url`） | PDF + MinerU 跳过下载 |
| `src/main.py` | — | `lifespan` | 修改 | — | — | 启动时调用 `temp_workspace.ensure_clean_on_startup(settings.PARSE_TEMP_DIR)` | worker 启动时清空 / 不存在则创建 |
| `src/config.py` | `Settings` | `PARSE_TEMP_DIR` | 新增 | — | — | 暴露配置 | （配置项，间接覆盖所有 Scenario） |

### 7.2 逐方法实现设计

#### 7.2.1 `services/storage/base.py::BaseObjectStorage.download_to_path`

- 当前行为：不存在；仅有 `download_bytes`。
- 修改后职责：抽象方法，要求驱动把对象内容流式写入指定本地 `Path`，不在内存中持有完整对象。
- 入参：`bucket: str, object_key: str, dst: pathlib.Path`
- 返回：`None`
- 详细步骤：抽象方法体仅 `pass`；约束在 docstring：实现必须保证整个调用栈内不出现"整对象 bytes"的内存对象。
- 事务与异常边界：实现可抛出对象存储 SDK 原生异常（404、403、网络等）；磁盘满（`OSError` errno=ENOSPC）也允许向上抛，由调用方分类。
- 调用关系：被 `ParseSourceIO.download_to_path` 调用。
- 对应测试：`tests/unit/services/storage/test_storage_download_to_path.py::test_minio_uses_download_fileobj`、`test_oss_uses_streaming_api`。

#### 7.2.2 `services/storage/minio_storage.py::MinioStorage.download_to_path`

- 修改后职责：使用 boto3 `client.download_fileobj` 分块拉取并写盘。
- 详细步骤：
  1. `dst.parent.mkdir(parents=True, exist_ok=True)`
  2. `with open(dst, "wb") as fp: self._client.download_fileobj(Bucket=bucket, Key=object_key, Fileobj=fp)`
  3. 不在函数内捕获 SDK 异常；磁盘满让 `OSError` 直接传出。
- 事务与异常边界：失败时 `dst` 可能存在半成品文件，由调用方 finally 清理。
- 对应测试：`test_minio_uses_download_fileobj`（mock boto3 client 验证调用入参 + 落盘大小）。

#### 7.2.3 `services/storage/oss_storage.py::OssStorage.download_to_path`

- 修改后职责：使用 oss2 SDK `bucket.get_object_to_file(key, dst)` 或等价流式接口。
- 详细步骤：若 OSS 适配器仍为占位，保留 `NotImplementedError("OSS 存储适配器尚未实现")` 一致语义即可（不强行实现）；但接口签名必须存在，避免抽象类 mismatch。
- 备注：本次完成"接口对齐 + 占位实现"；实际接入由生产侧另行触发。`brief.md` 第 4 章已认可"两家驱动同步改造"以接口为准。
- 对应测试：`test_oss_uses_streaming_api`——断言调用底层 `bucket.get_object_to_file` 或在占位实现下抛 `NotImplementedError`。

#### 7.2.4 `core/pipeline/parse_task/source.py::ParseSourceIO.download_to_path`

- 修改后职责：把 payload 中的 bucket / key 透传给底层 storage 的 path 版接口；自身不持有临时文件所有权。
- 入参：`(payload: ParseTaskPayload, dst: Path) -> None`
- 详细步骤：日志保留现有 `download file: bucket={} object_key={}` 风格，但日志位置不变（下载开始时打）；下载完成后的"file_size_mb / download_ms"日志在 pipeline 层负责（避免日志责任分裂）。
- 异常边界：直接抛底层异常，分类交给 pipeline。
- 对应测试：在 `test_pipeline_temp_file_lifecycle.py` 中 mock storage 验证 `dst` 路径在 PARSE_TEMP_DIR 下。

#### 7.2.5 `core/pipeline/parse_task/temp_workspace.py`（新增模块）

```python
# 文件骨架（非最终代码）
from pathlib import Path
import os, uuid
from loguru import logger

def ensure_clean_on_startup(temp_dir: Path) -> None:
    """worker 启动时确保 PARSE_TEMP_DIR 存在且为空。"""
    temp_dir.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in temp_dir.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink(missing_ok=True)
            removed += 1
        # 不递归删子目录：当前模块只产出平铺文件
    logger.info("[temp_workspace] startup clean: dir={} removed={}", temp_dir, removed)

def create_temp_file(task_id: str, temp_dir: Path) -> Path:
    """生成命名隔离的临时文件路径（未创建实际文件，交由 download_to_path 写入）。"""
    name = f"parse-{task_id}-{uuid.uuid4().hex[:8]}.tmp"
    return temp_dir / name

def safe_unlink(path: Path | None) -> None:
    """幂等删除：不存在不抛错；其他 OSError 上抛便于排查。"""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("[temp_workspace] unlink failed: path={} error={}", path, exc)
```

- 事务边界：函数级别幂等；启动清理失败应让 worker 启动失败，方便运维定位（mkdir 失败会自然抛出）。
- 对应测试：`test_temp_workspace.py::test_startup_clean_removes_residue / test_startup_creates_missing_dir`。

#### 7.2.6 `core/pipeline/parse_task/pipeline.py::ParseTaskPipeline._run`

- 当前行为：第 140–183 行调用 `self._source_io.download(payload)` 取 bytes、传给 `_parse_file(file_bytes, payload)`，再 `upload_markdown(parse_result["markdown"])`。
- 修改后职责：管理临时文件生命周期 + 错误分类 + 观测日志。
- 详细步骤（关键代码段伪码）：

  ```python
  source_path: Path | None = None
  if self._source_io.should_skip_source_download(payload):
      logger.info("[ParseTaskPipeline] skip source download (MinerU URL): task_id={}", payload.task_id)
  else:
      source_path = temp_workspace.create_temp_file(payload.task_id, settings.PARSE_TEMP_DIR)
      download_started_at = time.monotonic()
      try:
          await asyncio.to_thread(self._source_io.download_to_path, payload, source_path)
      except OSError as exc:
          temp_workspace.safe_unlink(source_path)
          if exc.errno == errno.ENOSPC:
              return await self._handle_execution_failure(
                  payload, log_record, db, ParseFailureCode.TEMP_DISK_FULL, exc,
              )
          # 其他 OSError（权限 / IO）归一到 SOURCE_FILE_NOT_FOUND
          return await self._handle_execution_failure(
              payload, log_record, db, ParseFailureCode.SOURCE_FILE_NOT_FOUND, exc,
          )
      except Exception as exc:
          temp_workspace.safe_unlink(source_path)
          return await self._handle_execution_failure(
              payload, log_record, db, ParseFailureCode.SOURCE_FILE_NOT_FOUND, exc,
          )
      download_ms = int((time.monotonic() - download_started_at) * 1000)
      file_size_mb = source_path.stat().st_size / (1024 * 1024)
      logger.info(
          "[ParseTaskPipeline] source downloaded: task_id={} file_size_mb={:.1f} download_ms={}",
          payload.task_id, file_size_mb, download_ms,
      )

  try:
      parse_started_at = time.monotonic()
      try:
          parse_result = await self._parse_file(source_path, payload)
      except Exception as exc:
          return await self._handle_execution_failure(
              payload, log_record, db, ParseFailureCode.PARSE_ENGINE_FAILED, exc,
          )
      parse_ms = int((time.monotonic() - parse_started_at) * 1000)
      logger.info(
          "[ParseTaskPipeline] parse completed: task_id={} parse_ms={} markdown_chars={}",
          payload.task_id, parse_ms, len(parse_result["markdown"] or ""),
      )
      # 早删：拿到 markdown 立即清理临时文件
      temp_workspace.safe_unlink(source_path)
      source_path = None
      # —— 以下 upload_markdown / post-process 保持原有逻辑 ——
      ...
  finally:
      # 二次兜底：异常路径未来得及早删时清理
      temp_workspace.safe_unlink(source_path)
  ```

- 事务与异常边界：
  - 下载 OSError + ENOSPC → `TEMP_DISK_FULL`
  - 下载其他异常 → `SOURCE_FILE_NOT_FOUND`
  - parse 异常 → `PARSE_ENGINE_FAILED`（同现有）
  - upload_markdown 异常 → `PARSED_FILE_UPLOAD_FAILED`（同现有，此时 source_path 已为 None，finally 不再删）
- 幂等与并发：临时文件名含 `task_id` + 随机 hex，无文件名碰撞。pipeline 自身不引入新的并发模型，仍由 MQ 消费侧决定。
- 调用关系：依赖 `ParseSourceIO.download_to_path`、`temp_workspace.*`、`error_codes.ParseFailureCode.TEMP_DISK_FULL`、现有 `_handle_execution_failure`。
- 对应测试：`test_pipeline_temp_file_lifecycle.py`（主流程 + 早删 + finally 兜底）、`test_pipeline_error_paths.py`（三类失败 + upload 失败 finally 不重复删）、`test_pipeline_observability.py`（两条日志字段断言）。

#### 7.2.7 `core/pipeline/parse_task/pipeline.py::ParseTaskPipeline._parse_file`

- 修改后职责：把 `source_path: Path | None` 透传给 `ParseTaskService.aprocess`；其余逻辑（parser_kwargs 构造）不变。
- 入参：`source_path: Path | None, payload: ParseTaskPayload`。
- 详细步骤：MinerU 旁路（`source_path is None`）时透传 `None`；非旁路传 path。`parser_kwargs` 的 `source_file_url` 构造逻辑不变。
- 对应测试：通过 7.2.6 的用例间接覆盖。

#### 7.2.8 `core/parser/base.py::IFileParser.parse` 与 `BaseParser.validate_source`

- 修改后职责：接受 `source: Path | None`，返回 markdown 字符串。
- `BaseParser.validate_source(source)`：
  - `source is None` 时不抛异常（MinerU 旁路场景）；
  - 非 None 时校验 `source.exists() and source.stat().st_size > 0`，否则抛 `ValueError("文件流不可为空")`（保持现有语义）。
- 对应测试：`test_parser_protocol_path.py::test_parse_rejects_bytes_input` + `test_validate_source_rules`。

#### 7.2.9 `core/parser/providers/word_parser.py::WordParser.parse`

- 修改后职责：`doc = docx.Document(str(source))`；删除所有 `BytesIO` 引用；其余 markdown 拼接逻辑保持不变。
- 对应测试：`test_pipeline_temp_file_lifecycle.py` 中 Outline 的 docx/doc examples。

#### 7.2.10 `core/parser/providers/html_parser.py::HtmlParser.parse`

- 修改后职责：`html_content = Path(source).read_text(encoding="utf-8", errors="ignore")`；其余 trafilatura 调用不变。
- 对应测试：Outline html example。

#### 7.2.11 `core/parser/providers/pdf_parser.py::PdfParser.parse`

- 修改后职责：
  - `can_skip_local_pdf = self.backend == "mineru" and bool(self.source_file_url) and source is None`
  - 非旁路：`doc = fitz.open(filename=str(source))` 用于 metadata 提取
  - 调用 `self._service.parse(source, options)` 透传 path

#### 7.2.12 `core/parser/pdf/service.py::PdfParserService.parse`

- 修改后职责：把 `source: Path | None` 透传给每个后端；旁路（`source is None`）下不调用 fitz / 不准备图像资产，直接调度 MinerU 后端。
- 详细步骤：`fitz.open(stream=...)` 全部替换为 `fitz.open(filename=str(source))`；`_prepare_image_uploads` / `_upload_images` 同步替换。
- 旁路保护：当前函数在 source 为 None 时已存在 `if not file_stream: return []` 分支（service.py:213），改造后等价为 `if source is None: return []`。

#### 7.2.13 PDF 三个 backends `.parse`

- `NaiveBackend.parse(source: Path, options)`：
  - `pymupdf4llm.to_markdown(str(source))` 直接传路径；删除 `tempfile.NamedTemporaryFile` 块。
  - `fitz.open(filename=str(source))`。
- `OpenDataLoaderBackend.parse(source: Path, options)`：
  - 删除 `pdf_path = temp_path / "document.pdf"; pdf_path.write_bytes(file_stream)`，改为 `pdf_path = source`（保留 `temp_dir` 仅用作 `output_dir` 隔离）。
  - 其余 `opendataloader_pdf.convert(input_path=[str(source)], output_dir=..., ...)` 不变。
- `MineruBackend.parse(source: Path | None, options)`：
  - 仅签名对齐；函数体不读 `source`，逻辑保持。

- 对应测试：`test_pipeline_temp_file_lifecycle.py` 的 Outline 4 类 examples 间接覆盖；PDF 单元层通过 mock 替换具体后端实现避免真实文件依赖。

#### 7.2.14 `src/main.py::lifespan`

- 修改后职责：在 `await init_database()` 之后、`await start_parse_consumer()` 之前调用：
  ```python
  from src.core.pipeline.parse_task import temp_workspace
  temp_workspace.ensure_clean_on_startup(Path(settings.PARSE_TEMP_DIR))
  ```
- 失败处理：mkdir 或清理失败让异常上抛，阻止 worker 启动（避免后续 download_to_path 永远失败但运维不知）。
- 对应测试：`test_temp_workspace.py` 直接对函数单测；lifespan 集成测试不在本次范围。

---

## 8. 组件与集成设计

| 组件 | 影响 | 集成方式 |
| :--- | :--- | :--- |
| MinIO（boto3） | 下载侧改为 `download_fileobj` 流式 | 现有 boto3 client 复用，无新增依赖 |
| OSS（oss2） | 接口对齐，占位实现保留 | 实际生产接入时再补 |
| MQ / Kafka | 无变化 | 消息契约不动 |
| FastAPI lifespan | 启动钩子追加临时目录清理 | 单行 import + 单行调用 |
| loguru | 已用，无新依赖 | 仅新增两条结构化日志 |
| 文件系统 | 新增 `PARSE_TEMP_DIR` 目录 | 启动钩子负责创建/清空 |

无新增第三方依赖。

---

## 9. 异常处理与降级策略

| 异常场景 | 处理方式 | 是否抛出 | 是否影响消息确认 |
| :--- | :--- | :--- | :--- |
| 对象存储 404 / 网络异常 | finally 删半成品；归 `SOURCE_FILE_NOT_FOUND` | 否，转为终态失败 + parse_result 通知 | 不重投（终态失败已写库） |
| 下载阶段 `OSError errno=ENOSPC` | finally 删半成品；归 **新错误码 `TEMP_DISK_FULL`** | 否，转为终态失败 + parse_result 通知 | 不重投 |
| parser 抛异常 | finally 删临时文件；归现有 `PARSE_ENGINE_FAILED` | 否，转为终态失败 | 不重投 |
| markdown 上传失败 | 临时文件已早删；归现有 `PARSED_FILE_UPLOAD_FAILED` | 否 | 不重投 |
| 进程 SIGKILL | 临时文件残留 | — | 下次 worker 启动时清空兜底 |
| `temp_workspace.ensure_clean_on_startup` 失败 | mkdir / 清空错误 | 是，让应用启动失败 | 拒绝消费消息 |
| `temp_workspace.safe_unlink` 失败 | 仅 logger.warning，不阻断 | 否 | 不影响 |

---

## 10. 测试方案

### 10.1 测试组织

本次**引入 `pytest-bdd>=7.0.0`** 作为 dev 依赖，`acceptance.feature` 升级为 pytest 直接加载的可执行验收契约：

- 测试入口：`tests/acceptance/test_parse_task_oom_governance.py`，仅一行 `scenarios("../../docs/解析任务OOM风险治理/acceptance.feature")` 自动把 17 条 Scenario 全部收集为 pytest case。
- Step 实现：`tests/acceptance/steps/*.py`，按"存储 / 流水线 / parser / 临时目录 / 日志"五个关注点拆分，避免单文件膨胀。
- Step 模式使用 pytest-bdd 的 `parsers.parse` / `parsers.re`，支持中文模式（acceptance.feature 头部已声明 `# language: zh-CN`）。
- 共享 fixture（`tests/acceptance/conftest.py`）：
  - `fake_storage`：实现 `download_to_path` 与 `download_bytes`（后者设为 `Mock` 用于断言"调用次数 == 0"）的桩
  - `payload_factory`：按 file_type / pdf_backend / size_mb 构造 `ParseTaskPayload`
  - `tmp_workspace`：在 `tmp_path` 下隔离 `PARSE_TEMP_DIR`，自动 monkeypatch `settings.PARSE_TEMP_DIR`
  - `caplog_loguru`：拦截 loguru sink，供日志字段断言
  - `pipeline_factory`：装配带桩依赖的 `ParseTaskPipeline`
- Scenario Outline 中的 `Examples` 表自动展开为参数化用例，pytest 收集时一条 example 对应一条 case。

Step 模块分工：

| Step 模块 | 关注 step 模式（示例） |
| :--- | :--- |
| `background_steps.py` | "配置 PARSE_TEMP_DIR = {path}"、"PARSE_TEMP_DIR 已存在且为空"、"ParseTaskPipeline 已初始化并连接到 MinIO 驱动" |
| `storage_steps.py` | "对象存储中存在源文件 size={n}MB"、"调用 storage.download_to_path(...)"、"底层调用 boto3 client.download_fileobj..." |
| `pipeline_steps.py` | "payload.file_type == ..."、"ParseTaskPipeline 执行该 payload"、"task 终态 status == ..."、"failure_reason 以 ... 开头" |
| `parser_steps.py` | "用 bytes 类型实参调用 parser.parse(...)"、"抛出 TypeError 或 AttributeError"、"返回 str 类型 markdown" |
| `temp_workspace_steps.py` | "PARSE_TEMP_DIR 在启动前包含残留文件 [...]"、"worker 进程启动"、"PARSE_TEMP_DIR 内文件数 == 0" |
| `logging_steps.py` | "loguru 日志中存在一条匹配 ... 的记录"、"该记录包含字段 file_size_mb 数值 ≈ ..." |

### 10.2 方法级测试映射

| 被测文件/方法 | 测试承接（pytest-bdd Scenario 名） | 测试文件 / Step 模块 | 断言要点 |
| :--- | :--- | :--- | :--- |
| `MinioStorage.download_to_path` | "MinIO 驱动实现 download_to_path 走 boto3 download_fileobj" | `steps/storage_steps.py` | mock client 验证 `download_fileobj` 被调用；落盘大小 |
| `OssStorage.download_to_path` | "OSS 驱动实现 download_to_path 走流式接口" | 同上 | 占位实现下断言 `NotImplementedError` 或 mock oss2 |
| `ParseSourceIO.download_to_path` | 主流程 Outline 4 examples + "非旁路路径不再调用全量 bytes 下载接口" | `steps/pipeline_steps.py` + `steps/storage_steps.py` | `dst` 在 PARSE_TEMP_DIR 下；`fake_storage.download_bytes` 调用次数 == 0 |
| `ParseTaskPipeline._run`（主流程） | "PDF + MinerU 后端跳过下载走 URL 旁路" / Outline 4 / "临时文件在 markdown 拿到后立即删除..." | `steps/pipeline_steps.py` | task.status==SUCCESS；解析后 PARSE_TEMP_DIR 不含该任务文件 |
| `ParseTaskPipeline._run`（异常） | "对象存储下载失败..." / "临时盘写满..." / "解析阶段抛异常..." / "markdown 上传失败..." | 同上 | failure_reason 前缀匹配；PARSE_TEMP_DIR 无残留；finally 不抛 FileNotFoundError |
| `IFileParser.parse` / 三个 provider | "parser 协议入参为 Path 不再接受 bytes" | `steps/parser_steps.py` | bytes 实参抛错；Path 实参返回 str |
| `temp_workspace.ensure_clean_on_startup` | "worker 启动时 PARSE_TEMP_DIR 存在残留文件被清空" / "...不存在则创建" | `steps/temp_workspace_steps.py` + `tests/unit/.../test_temp_workspace_unit.py` | 启动后目录存在且文件数 == 0；mkdir 行为正确 |
| 观测日志 | "下载完成日志包含文件大小与下载耗时字段" / "解析完成日志包含解析耗时与 markdown 字符数字段" | `steps/logging_steps.py` | loguru record 含 `file_size_mb` / `download_ms` / `parse_ms` / `markdown_chars` |
| `temp_workspace.safe_unlink` 幂等 | （内部边界，无业务 Scenario 自然表达） | `tests/unit/.../test_temp_workspace_unit.py` | 不存在路径 / None 入参不抛错；其他 OSError 上抛 |

### 10.3 Scenario 覆盖自检

pytest-bdd 在收集阶段会对 `acceptance.feature` 中**每条 Scenario** 生成对应的 pytest item。CI 中加入：

```bash
.venv/bin/pytest tests/acceptance --collect-only -q
```

预期至少收集到 17 条 case（Outline 展开为 4 条独立 example，其余为 1 对 1）。若任何 Scenario 未匹配到 step 实现，pytest-bdd 在收集时直接抛 `StepDefinitionNotFoundError`，CI 标红——**Scenario 全覆盖由 pytest-bdd 收集机制强制保证**，无需再手工维护 Scenario→测试映射表。

人工 review 只需关注：

- 每条 Scenario 在执行（非收集）阶段都通过
- step 定义没有"打桩通过"而无实际断言的情况（review step 实现时按 §10.2 表格的"断言要点"列对照）

### 10.4 回归命令

```bash
# 仅跑验收契约层（pytest-bdd 加载 acceptance.feature）
.venv/bin/pytest tests/acceptance -v

# 验收 + 单元
.venv/bin/pytest tests/unit tests/acceptance -v

# 全量
.venv/bin/pytest tests -q

# 文档同步自检
python scripts/check_docs_sync.py --staged
```

### 10.2 方法级测试映射

| 被测文件/方法 | 测试文件 | 对应 Scenario | 断言要点 |
| :--- | :--- | :--- | :--- |
| `MinioStorage.download_to_path` | `tests/unit/services/storage/test_storage_download_to_path.py` | MinIO 驱动实现 download_to_path 走 boto3 download_fileobj | mock client 验证调用入参；落盘大小 |
| `OssStorage.download_to_path` | 同上 | OSS 驱动实现 download_to_path 走流式接口 | mock oss2 或断言占位 `NotImplementedError` |
| `ParseSourceIO.download_to_path` | `tests/unit/core/pipeline/parse_task/test_pipeline_temp_file_lifecycle.py` | 非旁路四类文件类型流式下载（Outline 4 examples） | `dst` 在 PARSE_TEMP_DIR 下；调用次数 1 |
| `ParseTaskPipeline._run`（主流程） | 同上 | 非旁路四类文件类型流式下载 / PDF + MinerU 跳过下载 / 临时文件早删 | parse_result.status==SUCCESS；解析后 temp 不存在 |
| `ParseTaskPipeline._run`（异常） | `test_pipeline_error_paths.py` | 下载 404 → SOURCE_FILE_NOT_FOUND / 写满 → TEMP_DISK_FULL / parser 异常 / upload 失败 finally 不重复删 | failure_reason 前缀；PARSE_TEMP_DIR 无残留 |
| 内存治理断言 | 同上 + `test_parser_protocol_path.py` | 非旁路路径不再调用全量 bytes 下载接口 / parser 拒绝 bytes 入参 | mock `storage.download_bytes` 不被调用；`parse(b"...")` 抛 TypeError |
| 观测日志 | `test_pipeline_observability.py` | 下载完成日志字段 / 解析完成日志字段 | 捕获 loguru，断言 record 包含 `file_size_mb` / `download_ms` / `parse_ms` / `markdown_chars` |
| `temp_workspace.ensure_clean_on_startup` | `test_temp_workspace.py` | 启动时残留被清空 / 不存在则创建 | 启动后目录存在且文件数==0 |

### 10.3 Scenario 覆盖自检

| Scenario | 承接方法 | 承接测试 | 是否覆盖 |
| :--- | :--- | :--- | :--- |
| PDF + MinerU 后端跳过下载走 URL 旁路 | `ParseTaskPipeline._run` 旁路分支 + `PdfParser.parse` source=None | `test_pipeline_temp_file_lifecycle.py::test_mineru_url_bypass` | ✅ |
| 非旁路文件类型流式下载到临时文件并解析（Outline×4） | `_run` 非旁路分支 + 各 provider | `test_pipeline_temp_file_lifecycle.py::test_non_bypass_path[*]`（参数化） | ✅ |
| 临时文件在 markdown 拿到后立即删除而非等到 pipeline 终态 | `_run` 早删段 | `test_pipeline_temp_file_lifecycle.py::test_temp_file_deleted_before_postprocess` | ✅ |
| 对象存储下载失败归 SOURCE_FILE_NOT_FOUND 且清理临时文件 | `_run` 下载异常分支 | `test_pipeline_error_paths.py::test_download_404_classified` | ✅ |
| 临时盘写满触发新错误码 TEMP_DISK_FULL | `_run` OSError ENOSPC 分支 + `ParseFailureCode.TEMP_DISK_FULL` | `test_pipeline_error_paths.py::test_enospc_classified_as_temp_disk_full` | ✅ |
| 解析阶段抛异常时临时文件仍被清理 | `_run` finally 兜底 | `test_pipeline_error_paths.py::test_parse_exception_cleans_temp` | ✅ |
| markdown 上传失败时临时文件已删除不重复清理 | `_run` 早删 + finally 幂等 | `test_pipeline_error_paths.py::test_upload_failure_does_not_double_unlink` | ✅ |
| worker 启动时残留被清空 | `temp_workspace.ensure_clean_on_startup` | `test_temp_workspace.py::test_startup_clean_removes_residue` | ✅ |
| worker 启动时不存在则创建 | 同上 | `test_temp_workspace.py::test_startup_creates_missing_dir` | ✅ |
| 非旁路路径不再调用全量 bytes 下载接口 | `_run` + 协议层删除 `download_bytes` | `test_pipeline_temp_file_lifecycle.py::test_download_bytes_not_called` | ✅ |
| parser 协议入参为 Path 不再接受 bytes | `IFileParser.parse` + 各 provider | `test_parser_protocol_path.py::test_parse_rejects_bytes_input` | ✅ |
| 下载完成日志包含文件大小与下载耗时字段 | `_run` 日志段 | `test_pipeline_observability.py::test_download_log_fields` | ✅ |
| 解析完成日志包含解析耗时与 markdown 字符数字段 | 同上 | `test_pipeline_observability.py::test_parse_log_fields` | ✅ |
| MinIO 驱动实现 download_to_path 走 boto3 download_fileobj | `MinioStorage.download_to_path` | `test_storage_download_to_path.py::test_minio_uses_download_fileobj` | ✅ |
| OSS 驱动实现 download_to_path 走流式接口 | `OssStorage.download_to_path` | `test_storage_download_to_path.py::test_oss_uses_streaming_api` | ✅ |

无未覆盖 Scenario。

### 10.4 回归命令

```bash
# 单元测试（首选）
.venv/bin/pytest tests/unit/services/storage/test_storage_download_to_path.py \
                 tests/unit/core/parser/test_parser_protocol_path.py \
                 tests/unit/core/pipeline/parse_task/ -v

# 全量
.venv/bin/pytest tests -q

# 文档同步自检
python scripts/check_docs_sync.py --staged
```

---

## 11. 发布与回滚

### 11.1 发布顺序

0. 准备 dev 依赖：`pyproject.toml [project.optional-dependencies] dev` 加入 `pytest-bdd>=7.0.0`；`pip install -e ".[dev]"` 升级本地环境。
1. 合入存储层（`base.py` + `minio_storage.py` + `oss_storage.py`）+ `temp_workspace.py` 模块——独立可测。
2. 合入 parser 协议层（`base.py` + 三个 provider + PDF service / backends）——独立可测。
3. 合入 pipeline 编排层（`source.py` + `pipeline.py` + `error_codes.py` + `main.py` lifespan）——把前两步串起来。
4. 同步更新 `docs/architecture/parse_task_pipeline_module.md`、`docs/reference/error_codes.md`、`docs/guides/configuration.md`、`.env.example`、`docs/architecture/object_storage_module.md`、`docs/architecture/file_parser_module.md`。
5. 跑 `pytest tests -q` + `check_docs_sync.py --staged`，CI 通过后合入主干。

建议作为**单个 PR 一次性提交**（与 brief Q4 决策一致），三步在 PR 内分 commit 便于 review。

### 11.2 部署侧确认

- `.env` 增加 `PARSE_TEMP_DIR=/tmp/tolink-rag-parse`（不设也走默认值）。
- 容器 / 主机系统盘剩余空间应大于"单文件上限 × 当前 in-flight 任务数"，本次默认单消费者下 1× 即可。

### 11.3 回滚

代码回滚到合并前 commit 即可——本次不涉及数据迁移、不改 MQ 契约、不改 ORM。回滚后 Java 端遇到的 `failure_reason=TEMP_DISK_FULL:...` 会停止再出现，已有失败任务文案保留在历史日志中（不影响后续行为）。

---

## 12. 风险与待确认问题

| 风险/问题 | 影响 | 建议处理 |
| :--- | :--- | :--- |
| MinerU URL 旁路语义改变（旧 `file_stream=b""` → 新 `source_path=None`） | PDF + MinerU 路径行为是否完全等价存在认知差异 | `_run` 与 `PdfParser.parse` 中保留显式 `is None` 判定，并在单测覆盖"旁路场景下不调用 download_to_path 也不创建临时文件" |
| `tests/integration/services/test_minio_pdf_parse_integration.py` 现有用例可能依赖 `download_bytes` | 集成测试用例需同步修改 | 与代码同 PR 修改，并 grep `download_bytes(` 兜底 |
| OSS 驱动占位实现保留 `NotImplementedError` | 若生产真切到 OSS 会失败 | 与 brief 一致：本次不强行实现 OSS 真实功能，仅协议对齐；切换 OSS 时由独立改造项落地 |
| PDF backends 内部对路径的兼容性（pymupdf4llm / opendataloader_pdf） | 部分老版本可能强制要求 bytes | 实施前 grep 库 API 文档；当前主流版本均支持路径入参 |
| 已有调用 `parser.parse(bytes)` 的测试桩 | 协议破坏式替换会暴露遗漏 | 实施时全仓 grep `parse(b"`、`parse(file_stream=`、`download_bytes(`，统一收敛 |
| Java 端对 `TEMP_DISK_FULL` 未识别 | 业务后台展示原始字符串 | PR 描述中明确通知 Java 端，建议后续在 Java 端错误码字典里同步登记，但不阻塞本次发布 |
| 临时文件并发命名碰撞（极端 MQ 重投） | 同 task_id 短时间重投落到同一文件 | 命名带 `uuid4().hex[:8]` 随机后缀，碰撞概率忽略；finally 幂等删保证最终一致 |
| 中文 Gherkin step 模式编写复杂 | pytest-bdd 中 step pattern 含变量参数（如 `size={n}MB`）需用 `parsers.parse` 或 `parsers.re` | step 模块按关注点拆分（§10.1 表）；优先用 `parsers.parse("...size={size:d}MB")`，复杂模式（数值近似断言）用 `parsers.re` 兜底；review 时确认收集阶段无 `StepDefinitionNotFoundError` |
| acceptance.feature 路径在 `docs/` 下而非 `tests/` 下 | pytest-bdd 默认从测试文件相对路径加载 feature | `tests/acceptance/test_parse_task_oom_governance.py` 使用相对路径 `scenarios("../../docs/解析任务OOM风险治理/acceptance.feature")`，无需复制 / 软链 |

无阻塞性待确认问题。

---

## 13. 实施顺序

1. **基础设施**：新增 `core/pipeline/parse_task/temp_workspace.py`；改 `services/storage/base.py` 协议、`minio_storage.py`、`oss_storage.py` 实现；改 `config.py` 加 `PARSE_TEMP_DIR`；改 `.env.example`。
2. **错误码**：改 `core/pipeline/parse_task/error_codes.py` 新增 `TEMP_DISK_FULL`；同步 `docs/reference/error_codes.md`。
3. **Parser 协议**：改 `core/parser/base.py`、`providers/word_parser.py`、`providers/html_parser.py`、`providers/pdf_parser.py`、`pdf/service.py` 与三个 backends。
4. **流水线编排**：改 `source.py`、`pipeline.py`；改 `src/main.py::lifespan` 注入启动清理。
5. **测试**：
   - 先在 `pyproject.toml` 加 `pytest-bdd>=7.0.0`，`pip install -e ".[dev]"` 同步本地环境。
   - 新增 `tests/acceptance/` 目录骨架（含 `test_parse_task_oom_governance.py` 使用 `scenarios(...)` 加载 feature）。
   - 先跑 `pytest tests/acceptance --collect-only` 确认 17 条 Scenario 全部被收集（若漏 step 会在此阶段抛错）。
   - 实现 `steps/*.py`，按 step 报告逐项填补，最终 `pytest tests/acceptance -v` 全绿。
   - 补 `tests/unit/.../test_temp_workspace_unit.py` 内部边界单测，运行 `pytest tests -q`。
6. **文档同步**：`object_storage_module.md`、`parse_task_pipeline_module.md`、`file_parser_module.md`、`configuration.md`；`check_docs_sync.py --staged` 通过。
7. **联调与回归**：手工验证一次大 docx 真实下载链路；提交 PR。

---

## 14. 人工审核清单

- [ ] §3.1 改动文件目录树已确认
- [ ] §7.1 方法级变更总表已确认（含 Scenario 映射）
- [ ] §9 异常分类与现有错误码体系无冲突
- [ ] §10.3 Scenario 全覆盖自检无遗漏
- [ ] §11.1 发布顺序与单 PR 决策一致
- [ ] §12 风险表中"MinerU 旁路语义变更"与"PDF backends 路径兼容性"已被特别 review
