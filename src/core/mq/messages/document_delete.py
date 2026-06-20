"""文档删除通知消息（LINK-55，Java → Python）。

Java 软删原文件/数据集后，afterCommit 投递本消息，Python 据此删除解析域衍生产物。
消息为**扁平裸 JSON + snake_case，无信封**（与 ``parse_task`` 一致，区别于 chat_turn /
usage_report 的 ``{mq_type,mq_name,payload}`` 信封）。Java 侧契约见
``DocumentDeleteNotifyMQ.java``；字段对照 docs/api/mq_contracts.md「删除通知字段」节。
"""

import json
from typing import Literal, Optional, Protocol

from pydantic import Field, model_validator

from src.core.mq.exceptions import MQSerializationError
from src.core.mq.message import AbstractMessage, MessagePayload

DELETE_TYPE_DATASET = "dataset"
DELETE_TYPE_FILE = "file"


class DocumentDeletePayload(MessagePayload):
    """删除通知载荷。

    ``dataset`` 范围 Java 不下发 ``original_file_id``（fastjson 省略 null）；``file`` 范围必填。
    """

    delete_type: Literal["dataset", "file"] = Field(
        ..., title="删除范围", description="dataset（按数据集级联）/ file（按单文件）"
    )
    dataset_id: int = Field(..., title="数据集ID", description="所属数据集 id")
    user_id: int = Field(..., title="用户ID", description="操作用户 id（归属维度，删除时兜底校验）")
    original_file_id: Optional[int] = Field(
        None,
        title="原文件ID",
        description="被软删的原文件 id；仅 file 范围必填，dataset 范围为空",
    )

    model_config = {"title": "文档删除通知载荷"}

    @model_validator(mode="after")
    def _validate_scope(self) -> "DocumentDeletePayload":
        # file 范围必须定位到具体原文件；缺失即坏消息，反序列化阶段直接拒绝。
        if self.delete_type == DELETE_TYPE_FILE and self.original_file_id is None:
            raise ValueError("delete_type=file 必须携带 original_file_id")
        return self


class DocumentDeleteMessage(AbstractMessage):
    """文档删除 MQ 消息。"""

    MQ_NAME = "tolink.rag.document_delete"
    MQ_TYPE = "DOCUMENT_DELETE"

    def __init__(self, payload: DocumentDeletePayload):
        self._payload = payload

    @classmethod
    def get_mq_name(cls) -> str:
        return cls.MQ_NAME

    @classmethod
    def get_mq_type(cls) -> str:
        return cls.MQ_TYPE

    def get_payload(self) -> DocumentDeletePayload:
        return self._payload

    @classmethod
    def build(
        cls,
        delete_type: str,
        dataset_id: int,
        user_id: int,
        original_file_id: Optional[int] = None,
    ) -> "DocumentDeleteMessage":
        return cls(
            payload=DocumentDeletePayload(
                delete_type=delete_type,
                dataset_id=dataset_id,
                user_id=user_id,
                original_file_id=original_file_id,
            )
        )

    @classmethod
    def parse_msg(cls, raw: str) -> DocumentDeletePayload:
        """反序列化扁平裸 JSON；兼容带 payload 信封形态（防御性，与 parse_task 同款）。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MQSerializationError(f"消息 JSON 反序列化失败: {exc}") from exc

        if not isinstance(data, dict):
            raise MQSerializationError("消息必须是 JSON 对象")

        payload_data = data.get("payload", data)
        try:
            return DocumentDeletePayload(**payload_data)
        except Exception as exc:
            raise MQSerializationError(
                f"DocumentDeletePayload 字段校验失败: {exc}，原始消息前200字符: {raw[:200]}"
            ) from exc

    class MQReceiver(Protocol):
        async def on_document_delete(self, payload: "DocumentDeletePayload") -> None: ...
