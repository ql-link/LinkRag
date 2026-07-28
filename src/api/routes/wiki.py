"""Wiki 标题搜索、直属正文展开、Chunk 定位和整树读取路由。"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from src.api.recall_session_auth import SessionAuthContext, verify_session_token
from src.api.schemas.wiki import (
    WikiChunkLocationsRequest,
    WikiChunkLocationsResponse,
    WikiDocumentTreeResponse,
    WikiHeadingChunksResponse,
    WikiSearchRequest,
    WikiSearchResponse,
)
from src.application.recall_errors import CODE_INVALID_REQUEST, RecallApiError
from src.application.wiki_runtime import WikiRuntime, get_wiki_runtime

router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])
SchemaT = TypeVar("SchemaT", bound=BaseModel)
_HEADING_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


def _openapi_request_body(schema: type[BaseModel]) -> dict[str, object]:
    """为保留手工错误映射的 POST 路由补充既有请求 Schema。"""

    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": schema.model_json_schema(),
                }
            },
        }
    }


async def _parse_body(request: Request, schema: type[SchemaT]) -> SchemaT:
    """解析并按严格 Pydantic Schema 校验请求体，统一映射为 422。"""

    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise RecallApiError(422, CODE_INVALID_REQUEST, "request body is not valid JSON") from exc
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise RecallApiError(422, CODE_INVALID_REQUEST, "invalid request body") from exc


def _doc_id(value: str) -> int:
    """把路径参数转换为正整数文档 ID，非法值统一返回业务 422。"""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise RecallApiError(
            422, CODE_INVALID_REQUEST, "doc_id must be a positive integer"
        ) from exc
    if parsed <= 0:
        raise RecallApiError(422, CODE_INVALID_REQUEST, "doc_id must be a positive integer")
    return parsed


def _heading_key(value: str) -> str:
    """校验标题稳定业务键必须是 64 位小写十六进制字符串。"""

    if not _HEADING_KEY_RE.fullmatch(value):
        raise RecallApiError(
            422, CODE_INVALID_REQUEST, "heading_key must be 64 lowercase hex chars"
        )
    return value


def _success(payload: dict, schema: type[SchemaT], request_id: str) -> JSONResponse:
    """按冻结响应 Schema 序列化成功载荷并回传请求标识。"""

    content = schema.model_validate(payload).model_dump(mode="json")
    _omit_optional_none(content)
    return JSONResponse(content=content, headers={"X-Request-Id": request_id})


def _omit_optional_none(value: object) -> None:
    """只省略冻结契约明确声明为“条件出现”的空字段。"""

    if isinstance(value, dict):
        for key in ("next_cursor", "next_direct_chunk_cursor", "direct_chunk_preview_id"):
            if value.get(key) is None:
                value.pop(key, None)
        for nested in value.values():
            _omit_optional_none(nested)
    elif isinstance(value, list):
        for nested in value:
            _omit_optional_none(nested)


@router.post(
    "/search",
    response_model=WikiSearchResponse,
    openapi_extra=_openapi_request_body(WikiSearchRequest),
)
async def search_wiki(
    request: Request,
    ctx: SessionAuthContext = Depends(verify_session_token),
    runtime: WikiRuntime = Depends(get_wiki_runtime),
) -> JSONResponse:
    """在授权范围内执行标题优先、BM25 补充的 Wiki 搜索。"""

    body = await _parse_body(request, WikiSearchRequest)
    if not body.query.strip():
        raise RecallApiError(400, CODE_INVALID_REQUEST, "query is empty or blank")
    payload = await runtime.search(
        ctx,
        query=body.query,
        dataset_ids=body.dataset_ids,
        doc_ids=body.doc_ids,
        cursor=body.cursor,
    )
    return _success(payload, WikiSearchResponse, ctx.request_id)


@router.get(
    "/documents/{doc_id}/headings/{heading_key}/chunks",
    response_model=WikiHeadingChunksResponse,
)
async def expand_heading_chunks(
    doc_id: str,
    heading_key: str,
    cursor: str | None = None,
    ctx: SessionAuthContext = Depends(verify_session_token),
    runtime: WikiRuntime = Depends(get_wiki_runtime),
) -> JSONResponse:
    """分页读取指定标题的直属 Chunk，不递归进入子标题。"""

    parsed_doc_id = _doc_id(doc_id)
    parsed_heading_key = _heading_key(heading_key)
    payload = await runtime.expand_heading_chunks(
        ctx,
        doc_id=parsed_doc_id,
        heading_key=parsed_heading_key,
        cursor=cursor,
    )
    return _success(payload, WikiHeadingChunksResponse, ctx.request_id)


@router.post(
    "/chunk-locations",
    response_model=WikiChunkLocationsResponse,
    openapi_extra=_openapi_request_body(WikiChunkLocationsRequest),
)
async def locate_chunks(
    request: Request,
    ctx: SessionAuthContext = Depends(verify_session_token),
    runtime: WikiRuntime = Depends(get_wiki_runtime),
) -> JSONResponse:
    """批量返回可见 Chunk 的全部直接标题路径。"""

    body = await _parse_body(request, WikiChunkLocationsRequest)
    payload = await runtime.locate_chunks(
        ctx,
        chunk_ids=body.chunk_ids,
        dataset_ids=body.dataset_ids,
    )
    return _success(payload, WikiChunkLocationsResponse, ctx.request_id)


@router.get(
    "/documents/{doc_id}/tree",
    response_model=WikiDocumentTreeResponse,
)
async def get_document_tree(
    doc_id: str,
    ctx: SessionAuthContext = Depends(verify_session_token),
    runtime: WikiRuntime = Depends(get_wiki_runtime),
) -> JSONResponse:
    """读取一篇授权且解析成功文档的完整 Wiki 标题树。"""

    parsed_doc_id = _doc_id(doc_id)
    payload = await runtime.get_document_tree(ctx, doc_id=parsed_doc_id)
    return _success(payload, WikiDocumentTreeResponse, ctx.request_id)
