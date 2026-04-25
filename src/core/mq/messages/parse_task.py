import json
from typing import Optional, Protocol

from pydantic import AliasChoices, Field

from src.core.mq.exceptions import MQSerializationError
from src.core.mq.message import AbstractMessage, MessagePayload


class ParseTaskPayload(MessagePayload):
    """文档解析任务载荷。"""

    task_id: str = Field(..., title="任务ID", description="文档解析任务的唯一标识")
    original_file_id: int = Field(..., title="原始文件ID", description="原始文件表主键")
    file_type: str = Field(..., title="文件类型", description="文件格式（pdf/docx/html/...）")
    source_bucket: str = Field(..., title="原始文件Bucket", description="源文件对象存储 bucket")
    source_object_key: str = Field(..., title="原始文件对象Key", description="源文件对象存储 key")
    source_filename: str = Field(..., title="原始文件名", description="用户上传时的原始文件名")
    md_bucket: str = Field(..., title="Markdown Bucket", description="Markdown 输出 bucket")
    md_object_key: str = Field(..., title="Markdown 对象Key", description="Markdown 输出对象 key")
    pdf_parser_backend: Optional[str] = Field(
        "mineru",
        title="PDF解析器",
        description="可选 PDF 解析器: mineru/naive",
        validation_alias=AliasChoices("pdf_parser_backend", "parser_backend"),
        serialization_alias="pdf_parser_backend",
    )
    docling_force_ocr: Optional[bool] = Field(
        False, title="Docling强制全页 OCR", description="仅 Docling 后端生效"
    )
    image_bucket: Optional[str] = Field(
        None, title="图片 Bucket", description="PDF 图片输出 bucket"
    )
    image_prefix: Optional[str] = Field(
        None, title="图片前缀", description="PDF 图片输出对象 key 前缀"
    )

    model_config = {"title": "文档解析任务载荷"}


class ParseTaskMessage(AbstractMessage):
    """文档解析 MQ 消息。"""

    MQ_NAME = "tolink.rag.parse_task"
    MQ_TYPE = "PARSE_TASK"

    def __init__(self, payload: ParseTaskPayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> ParseTaskPayload:
        return self._payload

    def get_routing_key(self) -> Optional[str]:
        return self._payload.file_type

    @classmethod
    def build(
        cls,
        task_id: str,
        original_file_id: int,
        file_type: str,
        source_bucket: str,
        source_object_key: str,
        source_filename: str,
        md_bucket: str,
        md_object_key: str,
        pdf_parser_backend: Optional[str] = "mineru",
        docling_force_ocr: Optional[bool] = False,
        image_bucket: Optional[str] = None,
        image_prefix: Optional[str] = None,
    ) -> "ParseTaskMessage":
        return cls(
            payload=ParseTaskPayload(
                task_id=task_id,
                original_file_id=original_file_id,
                file_type=file_type,
                source_bucket=source_bucket,
                source_object_key=source_object_key,
                source_filename=source_filename,
                md_bucket=md_bucket,
                md_object_key=md_object_key,
                pdf_parser_backend=pdf_parser_backend,
                docling_force_ocr=docling_force_ocr,
                image_bucket=image_bucket,
                image_prefix=image_prefix,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> ParseTaskPayload:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MQSerializationError(f"消息 JSON 反序列化失败: {exc}") from exc

        if not isinstance(data, dict):
            raise MQSerializationError("消息必须是 JSON 对象")

        payload_data = data.get("payload", data)
        try:
            return ParseTaskPayload(**payload_data)
        except Exception as exc:
            raise MQSerializationError(
                f"ParseTaskPayload 字段校验失败: {exc}，原始消息前200字符: {raw[:200]}"
            ) from exc

    class MQReceiver(Protocol):
        async def on_parse_task(self, payload: "ParseTaskPayload") -> None: ...
