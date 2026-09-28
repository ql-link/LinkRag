"""Java-compatible B4 dataset and parse-config routes."""

from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from src.api.management_auth import CurrentUser, require_login
from src.api.management_http import BusinessError, ManagementRouter, success
from src.application import datasets
from src.application.document_deletion import delete_dataset
from src.config import settings

router = ManagementRouter(prefix="/api/v1/datasets", tags=["datasets"])


def _write_ready() -> None:
    if not settings.B4_DATASET_WRITES_ENABLED:
        raise BusinessError(503, "数据集写入尚未切流", 503)


class CreateDatasetBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    sparse_embedding_config_id: int = Field(
        validation_alias=AliasChoices("sparse_embedding_config_id", "sparseEmbeddingConfigId")
    )
    dense_embedding_config_id: int = Field(
        validation_alias=AliasChoices("dense_embedding_config_id", "denseEmbeddingConfigId")
    )


class UpdateDatasetBody(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)


class ParseConfigBody(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    sparse_embedding_config_id: int = Field(
        validation_alias=AliasChoices("sparse_embedding_config_id", "sparseEmbeddingConfigId")
    )
    dense_embedding_config_id: int = Field(
        validation_alias=AliasChoices("dense_embedding_config_id", "denseEmbeddingConfigId")
    )
    enhancement_chat_config_id: int | None = Field(
        default=None, validation_alias=AliasChoices("enhancement_chat_config_id", "enhancementChatConfigId")
    )
    enhancement_vision_config_id: int | None = Field(
        default=None, validation_alias=AliasChoices("enhancement_vision_config_id", "enhancementVisionConfigId")
    )
    rerank_config_id: int | None = Field(
        default=None, validation_alias=AliasChoices("rerank_config_id", "rerankConfigId")
    )
    chunking: dict[str, Any] | None = None
    enhancement: dict[str, Any] | None = None
    pdf: dict[str, Any] | None = None
    recall: dict[str, Any] | None = None


@router.get("")
async def list_datasets(
    user: Annotated[CurrentUser, Depends(require_login)],
    page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
):
    return success(await datasets.list_datasets(user.user_id, page, pageSize))


@router.post("")
async def create_dataset(
    body: CreateDatasetBody, user: Annotated[CurrentUser, Depends(require_login)],
):
    _write_ready()
    return success(await datasets.create_dataset(
        user.user_id, body.name, body.description,
        body.dense_embedding_config_id, body.sparse_embedding_config_id,
    ))


@router.get("/{dataset_id}")
async def detail(
    dataset_id: int, user: Annotated[CurrentUser, Depends(require_login)],
):
    return success(await datasets.detail(user.user_id, dataset_id))


@router.patch("/{dataset_id}")
async def update_dataset(
    dataset_id: int, body: UpdateDatasetBody,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    _write_ready()
    return success(await datasets.update_dataset(
        user.user_id, dataset_id, body.model_dump(exclude_unset=True)
    ))


@router.get("/{dataset_id}/parse-config")
async def get_parse_config(
    dataset_id: int, user: Annotated[CurrentUser, Depends(require_login)],
):
    return success(await datasets.get_parse_config(user.user_id, dataset_id))


@router.put("/{dataset_id}/parse-config")
async def update_parse_config(
    dataset_id: int, body: ParseConfigBody,
    user: Annotated[CurrentUser, Depends(require_login)],
):
    _write_ready()
    return success(await datasets.update_parse_config(
        user.user_id, dataset_id, body.model_dump(exclude_unset=True)
    ))


@router.delete("/{dataset_id}")
async def delete(
    dataset_id: int, user: Annotated[CurrentUser, Depends(require_login)],
):
    if not settings.B5_DELETE_WRITES_ENABLED:
        raise BusinessError(503, "数据集删除尚未切流", 503)
    await delete_dataset(user.user_id, dataset_id)
    return success()
