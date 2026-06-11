# Object Storage Module

本文说明 `src/services/storage` 对象存储抽象的架构、使用方式和扩展规则。

## 1. 模块框架

```text
src/services/storage/
├── base.py          # BaseObjectStorage 抽象接口
├── factory.py       # StorageFactory 按配置选择实现
├── minio_storage.py # MinIO / S3 兼容实现
└── oss_storage.py   # OSS 适配器占位实现
```

主要调用方：

```text
ParseTaskPipeline
  -> StorageFactory.get_storage()
  -> download_to_path() / upload_bytes() / build_object_url()

PdfParserService
  -> upload_bytes()
  -> build_object_url()
```

## 2. 核心接口

`BaseObjectStorage` 定义三个方法：

```python
download_to_path(bucket: str, object_key: str, dst: pathlib.Path) -> None
upload_bytes(bucket: str, object_key: str, content: bytes, content_type: str) -> None
build_object_url(bucket: str, object_key: str) -> str
```

约定：

- `download_to_path` 流式落盘，**实现必须保证整个调用栈不持有完整对象 bytes**，避免大文件
  场景下 worker OOM。磁盘满（`OSError errno=ENOSPC`）允许向上抛，由调用方分类为
  `TEMP_DISK_FULL`；对象 404 / 网络异常向上抛归类为 `SOURCE_FILE_NOT_FOUND`。原
  `download_bytes` 已于"解析任务 OOM 风险治理"中下线。
- `upload_bytes` 负责写入对象和 content type；markdown 上传体积小（KB 级），保持现状。
- `build_object_url` 返回服务内部或外部可访问 URL；MinerU 官方云端解析依赖该 URL 可被外部访问。

## 3. 当前实现

| 实现 | 文件 | 说明 |
| --- | --- | --- |
| `MinioStorage` | `minio_storage.py` | 使用 boto3 S3 兼容客户端访问 MinIO |
| `OssStorage` | `oss_storage.py` | 占位实现，当前方法均抛 `NotImplementedError` |

`StorageFactory.get_storage()` 根据 `settings.STORAGE_TYPE` 选择实现：

- `minio` -> `MinioStorage`
- `oss` -> `OssStorage`

## 4. 配置

配置来自 `src/config.py::Settings`：

- `STORAGE_TYPE`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET_NAME`
- `MINIO_BLOG_BUCKET`
- `MINIO_USE_SSL`
- `LOCAL_DOCS_PATH`

MinIO endpoint 可带 `http://` 或 `https://`；不带 scheme 时由 `MINIO_USE_SSL` 决定。
`MINIO_BUCKET_NAME` 是 RAG 文档默认桶，也是 Python 侧非 `md`/`markdown` 解析产物的实际写入桶；
`MINIO_BLOG_BUCKET` 对齐 Java 博客模块的公开读桶（默认 `tolink-blog`）。

## 5. 在解析链路中的使用

源文件（流式下载到 `PARSE_TEMP_DIR` 临时文件，解析完成后立即清理）：

```text
ParseTaskPipeline._run()
  -> temp_workspace.create_temp_file(task_id, PARSE_TEMP_DIR)
  -> storage.download_to_path(source_bucket, source_object_key, dst=tmp_path)
  -> parser.parse(tmp_path)
  -> temp_workspace.safe_unlink(tmp_path)  # 拿到 markdown 后早删；finally 兜底
```

MinerU URL 直拉：

```text
ParseTaskPipeline._parse_file()
  -> storage.build_object_url(source_bucket, source_object_key)
  -> PdfParser(source_file_url=...)
```

Markdown 输出：

```text
ParseTaskPipeline._upload_markdown()
  -> storage.upload_bytes(MINIO_BUCKET_NAME, md_object_key, markdown, "text/markdown")
```

PDF 图片资产：

```text
PdfParserService
  -> storage.upload_bytes(image_bucket, image_object_key, image_bytes, content_type)
  -> storage.build_object_url(image_bucket, image_object_key)
```

## 6. 新增存储后端

1. 新增实现类并继承 `BaseObjectStorage`。
2. 实现下载、上传和 URL 构造三个方法。
3. 在 `StorageFactory.get_storage()` 中接入 `STORAGE_TYPE`。
4. 在 `src/config.py` 和 `.env.example` 增加必要配置。
5. 补充单元测试和真实环境集成测试。

新增后端不得把凭据写入文档、测试或提交配置；所有密钥必须走环境变量或安全配置。

## 7. 测试建议

```bash
.venv/bin/pytest tests/integration/services/test_minio_pdf_parse_integration.py -q
```

建议覆盖：

- 下载 PDF bytes。
- 上传 Markdown。
- URL 构造对中文、空格和特殊字符 object key 的编码。
- MinerU URL 直拉时 URL 的外部可访问性。
