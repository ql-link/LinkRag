from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SendParseTaskRequest(BaseModel):
    """文档解析任务消息发送请求。"""

    task_id: str = Field(..., title="任务ID", description="文档解析任务唯一标识")
    original_file_id: int = Field(..., title="原始文件ID", description="原始文件表主键")
    document_parse_task_id: int = Field(
        ...,
        title="文件解析表ID",
        description="document_parse_file 表主键",
        validation_alias=AliasChoices("document_parse_file_id", "document_parse_task_id"),
        serialization_alias="document_parse_file_id",
    )
    user_id: int = Field(..., title="用户ID", description="文件所属用户ID")
    dataset_id: int = Field(..., title="数据集ID", description="文件所属数据集ID")
    file_type: str = Field(..., title="文件类型", description="文件格式 (pdf/docx/html/...)")
    source_bucket: str = Field(..., title="源文件Bucket", description="原始文件所在对象存储 bucket")
    source_object_key: str = Field(..., title="源文件对象Key", description="原始文件对象存储 key")
    source_filename: str = Field(..., title="原始文件名", description="用户上传时的原始文件名")
    md_bucket: str = Field(
        ...,
        title="Markdown Bucket",
        description="历史兼容字段；Python 侧 Markdown 输出 bucket 使用 MINIO_BUCKET_NAME",
    )
    md_object_key: str = Field(..., title="Markdown 对象Key", description="Markdown 输出对象 key")
    trigger_mode: str = Field(
        "upload_auto", title="触发方式", description="upload_auto/manual_retry"
    )
    pdf_parser_backend: str = Field(
        "mineru",
        title="PDF解析器",
        description="可选 PDF 解析器: mineru/opendataloader/naive",
        validation_alias=AliasChoices("pdf_parser_backend", "parser_backend"),
        serialization_alias="pdf_parser_backend",
    )
    docling_force_ocr: bool = Field(
        False, title="Docling强制全页OCR", description="仅 docling 后端生效"
    )
    image_bucket: Optional[str] = Field(None, title="图片Bucket", description="PDF 图片输出 bucket")
    image_prefix: Optional[str] = Field(
        None, title="图片前缀", description="PDF 图片输出对象 key 前缀"
    )

    model_config = ConfigDict(title="发送解析任务请求体", populate_by_name=True)


class SendCacheSyncRequest(BaseModel):
    """缓存同步消息发送请求。"""

    user_id: str = Field(..., title="用户ID", description="需要同步缓存的用户标识")
    action: str = Field("refresh", title="操作类型", description="refresh / invalidate / warmup")
    config_id: Optional[str] = Field(None, title="配置ID", description="具体配置标识")

    model_config = ConfigDict(title="发送缓存同步请求体", populate_by_name=True)


class SendUsageReportRequest(BaseModel):
    """用量上报消息发送请求。"""

    user_id: str = Field(..., title="用户ID")
    provider_type: str = Field(..., title="LLM厂商类型")
    model_name: str = Field(..., title="模型名称")
    prompt_tokens: int = Field(0, ge=0, title="输入Token数")
    completion_tokens: int = Field(0, ge=0, title="输出Token数")
    total_tokens: int = Field(0, ge=0, title="总Token数")

    model_config = ConfigDict(title="发送用量上报请求体", populate_by_name=True)


class SendRawMessageRequest(BaseModel):
    """原始消息发送请求。"""

    topic: str = Field(..., title="目标Topic/Queue", description="消息投递目标")
    message: str = Field(..., title="消息体", description="JSON 字符串格式的消息内容")
    key: Optional[str] = Field(
        None, title="路由键", description="Kafka partition key / RabbitMQ routing key"
    )

    model_config = ConfigDict(title="原始消息发送请求体", populate_by_name=True)


class MQResponse(BaseModel):
    """MQ 操作响应。"""

    success: bool = Field(..., title="操作结果")
    message: str = Field("", title="描述信息")

    model_config = ConfigDict(title="MQ操作响应", populate_by_name=True)


class MQVendorInfoResponse(BaseModel):
    """MQ 厂商信息响应。"""

    current_vendor: str = Field(..., title="当前厂商", description="当前激活的 MQ 厂商")
    available_vendors: list[str] = Field(..., title="可用厂商列表")

    model_config = ConfigDict(title="MQ厂商信息响应", populate_by_name=True)
