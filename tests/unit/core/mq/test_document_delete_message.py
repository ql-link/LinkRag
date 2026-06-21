"""DocumentDeleteMessage 反序列化单测（LINK-55）。

覆盖：扁平裸 JSON（Java 投递形态）、带 payload 信封（防御兼容）、坏消息（缺
original_file_id / 非法 delete_type / 非 JSON / 非对象）。
"""

import json

import pytest

from src.core.mq.exceptions import MQSerializationError
from src.core.mq.messages import DocumentDeleteMessage, DocumentDeletePayload


class TestParseFlat:
    def test_dataset_scope_flat(self):
        raw = json.dumps({"delete_type": "dataset", "dataset_id": 10, "user_id": 100})
        payload = DocumentDeleteMessage.parse_msg(raw)
        assert payload.delete_type == "dataset"
        assert payload.dataset_id == 10
        assert payload.user_id == 100
        assert payload.original_file_id is None

    def test_file_scope_flat(self):
        raw = json.dumps(
            {"delete_type": "file", "dataset_id": 200, "user_id": 100, "original_file_id": 1}
        )
        payload = DocumentDeleteMessage.parse_msg(raw)
        assert payload.delete_type == "file"
        assert payload.original_file_id == 1

    def test_envelope_form_is_tolerated(self):
        raw = json.dumps(
            {
                "mq_type": "DOCUMENT_DELETE",
                "mq_name": "tolink.rag.document_delete",
                "payload": {"delete_type": "dataset", "dataset_id": 5, "user_id": 9},
            }
        )
        payload = DocumentDeleteMessage.parse_msg(raw)
        assert payload.dataset_id == 5
        assert payload.user_id == 9


class TestBadMessages:
    def test_file_scope_missing_original_file_id_rejected(self):
        raw = json.dumps({"delete_type": "file", "dataset_id": 1, "user_id": 1})
        with pytest.raises(MQSerializationError):
            DocumentDeleteMessage.parse_msg(raw)

    def test_invalid_delete_type_rejected(self):
        raw = json.dumps({"delete_type": "all", "dataset_id": 1, "user_id": 1})
        with pytest.raises(MQSerializationError):
            DocumentDeleteMessage.parse_msg(raw)

    def test_missing_ownership_rejected(self):
        raw = json.dumps({"delete_type": "dataset", "dataset_id": 1})
        with pytest.raises(MQSerializationError):
            DocumentDeleteMessage.parse_msg(raw)

    def test_non_json_rejected(self):
        with pytest.raises(MQSerializationError):
            DocumentDeleteMessage.parse_msg("not-json")

    def test_non_object_rejected(self):
        with pytest.raises(MQSerializationError):
            DocumentDeleteMessage.parse_msg("[1, 2, 3]")


def test_build_roundtrip():
    msg = DocumentDeleteMessage.build(
        delete_type="file", dataset_id=2, user_id=3, original_file_id=4
    )
    assert msg.get_mq_name() == "tolink.rag.document_delete"
    assert msg.get_mq_type() == "DOCUMENT_DELETE"
    assert isinstance(msg.get_payload(), DocumentDeletePayload)
    assert msg.get_payload().original_file_id == 4
