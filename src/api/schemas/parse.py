from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class TaskSubmitRequest(BaseModel):
    """异步解析任务提交请求。"""

    task_id: str = Field(..., title="任务ID", description="文档解析任务唯一标识")
    original_file_id: int = Field(..., title="原始文件ID", description="原始文件表主键")
    document_parse_task_id: int = Field(
        ..., title="文件解析表ID", description="document_parse_file 表主键，字段名保持历史兼容"
    )
    user_id: int = Field(..., title="用户ID", description="文件所属用户ID")
    dataset_id: int = Field(..., title="数据集ID", description="文件所属数据集ID")
    file_type: str = Field(..., title="文件类型", description="文件格式 (pdf/docx/html/txt)")
    source_bucket: str = Field(..., title="源文件Bucket", description="原始文件所在对象存储 bucket")
    source_object_key: str = Field(..., title="源文件对象Key", description="原始文件对象存储 key")
    source_filename: str = Field(..., title="原始文件名", description="用户上传的原始文件名")
    md_bucket: str = Field(..., title="Markdown Bucket", description="Markdown 输出 bucket")
    md_object_key: str = Field(..., title="Markdown 对象Key", description="Markdown 输出对象 key")
    trigger_mode: str = Field(
        "upload_auto", title="触发方式", description="upload_auto/manual_retry"
    )
    pdf_parser_backend: str = Field(
        "opendataloader",
        title="PDF解析器",
        description="可选 PDF 解析器: mineru/opendataloader/naive",
        validation_alias=AliasChoices("pdf_parser_backend", "parser_backend"),
        serialization_alias="pdf_parser_backend",
    )
    docling_force_ocr: bool = Field(
        False, title="Docling强制全页OCR", description="仅 docling 后端生效"
    )
    image_bucket: str | None = Field(None, title="图片Bucket", description="PDF 图片输出 bucket")
    image_prefix: str | None = Field(
        None, title="图片前缀", description="PDF 图片输出对象 key 前缀"
    )

    model_config = ConfigDict(title="异步解析任务请求体", populate_by_name=True)


class TaskSubmitResponse(BaseModel):
    """异步解析任务提交响应。"""

    code: int = Field(200, title="状态码")
    message: str = Field("", title="描述信息")
    data: dict = Field(default_factory=dict, title="响应数据")

    model_config = ConfigDict(title="异步解析任务响应体", populate_by_name=True)
