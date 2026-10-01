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

`BaseObjectStorage` 定义以下方法（另外保留按前缀删除）：

```python
download_to_path(bucket: str, object_key: str, dst: pathlib.Path) -> None
upload_bytes(bucket: str, object_key: str, content: bytes, content_type: str) -> None
build_object_url(bucket: str, object_key: str) -> str
upload_path(bucket: str, object_key: str, source: pathlib.Path, content_type: str) -> None
remove_object(bucket: str, object_key: str) -> None
build_public_url(bucket: str, object_key: str) -> str
```

约定：

- `download_to_path` 流式落盘，**实现必须保证整个调用栈不持有完整对象 bytes**，避免大文件
  场景下 worker OOM。磁盘满（`OSError errno=ENOSPC`）允许向上抛，由调用方分类为
  `TEMP_DISK_FULL`；对象 404 / 网络异常向上抛归类为 `SOURCE_FILE_NOT_FOUND`。原
  `download_bytes` 已于"解析任务 OOM 风险治理"中下线。
- `upload_bytes` 负责写入对象和 content type；markdown 上传体积小（KB 级），保持现状。
- `build_object_url` 返回服务内部或外部可访问 URL；MinerU 官方云端解析依赖该 URL 可被外部访问。
- `upload_path` 从路径流式上传大对象；在异步 API 中调用同步 boto3 方法时应移到 worker thread。
- `remove_object` 只删除非空、非目录的精确 key；S3 删除不存在对象仍可幂等成功。
- `build_public_url` 只接受 `MINIO_PUBLIC_BUCKET`，且必须显式设置 `MINIO_PUBLIC_BASE_URL`。
  `MINIO_PUBLIC_BASE_URL` 是公开资源路由前缀，返回值为此前缀加对象 key，不再插入桶名，
  与 Java `public-base-url` 保持一致。公开 URL 不回退到内部 MinIO 地址，私有桶不得调用此方法。

## 3. 当前实现

| 实现 | 文件 | 说明 |
| --- | --- | --- |
| `MinioStorage` | `minio_storage.py` | 使用 boto3 S3 兼容客户端访问 MinIO |
| `OssStorage` | `oss_storage.py` | 占位实现，当前方法均抛 `NotImplementedError` |

`StorageFactory.get_storage()` 根据 `settings.STORAGE_TYPE` 选择实现：

- `minio` -> `MinioStorage`
- `oss` -> 明确拒绝（占位实现尚不可用于运行环境）

应用启动时调用 `StorageFactory.validate_provider()`，因此选择 `oss` 或未知 provider
会在拉起 MQ 消费者之前失败。

## 4. 配置

配置来自 `src/config.py::Settings`：

- `STORAGE_TYPE`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_PRIVATE_BUCKET`
- `MINIO_RAW_BUCKET`
- `MINIO_PUBLIC_BUCKET`
- `MINIO_PUBLIC_BASE_URL`
- `MINIO_USE_SSL`
- `MINIO_PUBLIC_ENDPOINT`

MinIO endpoint 可带 `http://` 或 `https://`；不带 scheme 时由 `MINIO_USE_SSL` 决定。
`MINIO_PUBLIC_ENDPOINT` 可选，仅用于 `build_object_url` 生成给云端解析器或浏览器访问的对象 URL；为空时复用 `MINIO_ENDPOINT`。S3 SDK 读写仍固定使用 `MINIO_ENDPOINT`，避免公网反向代理影响签名请求。
`MINIO_PRIVATE_BUCKET` 是 RAG 文档默认桶，也是 Python 侧全部格式（含 `md`/`markdown`）解析产物的实际写入桶；
`MINIO_RAW_BUCKET` 是 Java 写、Python 只读的原文件桶。Markdown v1 的规范化源文件和配套图片都在此桶，Python 不通过 Java HTTP 或预签名 URL 取图；
`MINIO_PUBLIC_BUCKET` 默认 `tolink-public`，用于后续头像、博客等公开资源业务；Dev 与 Java 对齐为 `tolink-dev-public`。
`MINIO_PUBLIC_BASE_URL` 是其浏览器路由前缀，可以是同源相对路径 `/api/v1/oss-files/public` 或网关完整地址；为空时公开 URL 构造失败。
Dev 公开桶没有匿名读取策略，不能直接把 MinIO 桶 URL 返回给浏览器。Python 在 `B2_PUBLIC_PREVIEW_ENABLED=true` 时复用 `StorageFactory`，只从 PUBLIC 桶读取 `/api/v1/oss-files/public/{objectKey}`，按后缀返回 Content-Type；公开路径的网关切流须与该开关配套。该路由不访问 RAW/PRIVATE。生产环境若已有网关公开路由，也可保持该开关关闭。
开发 Web Nginx 将历史 `/tolink-dev-public/{objectKey}` 地址兼容转发到上述 Python 预览接口，保留存量图片链接可用；该路径同样依赖 `B2_PUBLIC_PREVIEW_ENABLED=true`，无需为 MinIO 桶增加匿名读取策略。直接访问 MinIO 桶地址仍受桶权限约束。

迁移中的 B2 通用上传复用同一 `StorageFactory`。`src/application/object_uploads.py` 保存 Java 的六类业务规则：`avatar`、`providerIcon`、`chatImage` 为 PUBLIC 图片 5 MiB；`feedback` 为 PUBLIC 指定后缀 10 MiB；`document` 为 RAW 的 `pdf/doc/docx/txt/md`、上限 20 MiB；`cert` 为 PRIVATE 5 MiB。PUBLIC 返回公开 URL，RAW/PRIVATE 只返回对象 key。`B2_GENERIC_UPLOAD_ENABLED=false` 默认关闭兼容入口，待匿名访问权限矩阵和网关切流确认后启用；B1 头像已复用其校验和上传流程。

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
  -> storage.upload_bytes(MINIO_PRIVATE_BUCKET, md_object_key, markdown, "text/markdown")
```

Markdown v1 RAW 图片读取：

```text
CleaningStage (仅 enable_image_enhancement=true)
  -> 校验 source_object_key == markdown-assets/v1/user-{u}/dataset-{d}/file-{f}/source/normalized.md
  -> 校验 tolink-raw://raw/... 仅指向同一 fileId 的 images/image-{sha256}.{ext}
  -> download_to_path(MINIO_RAW_BUCKET, image_object_key, task_temp_path)
  -> jpg/png/gif/webp 保留原字节；bmp/tiff 解码后转 image/png
  -> 当前 Vision batch 完成后释放字节；临时文件始终 safe_unlink
```

逻辑 URI 不含真实桶名、凭据或预签名参数。任何范围校验失败都不得调用存储接口；单图读取失败不阻断文本清洗和分片。

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
