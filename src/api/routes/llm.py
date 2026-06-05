"""
LLM API 路由
提供 LLM 调用接口：文本生成、向量化、重排等
"""
from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.llm.response import APIResponse
from src.core.llm.base_provider import BaseProvider
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.user_model_resolver import aresolve_user_model
from src.database import get_db

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


def _coerce_int(value: str, field: str) -> int:
    """把请求边界传入的 ID 字符串归一成 int，非法值 → 422。

    ``user_id``（来自 ``X-User-Id`` Header）与 ``config_id``（来自请求体）在路由层是
    字符串，但下游 resolver / ConfigReaderService / ``BigInteger`` 主键都按 int 契约。
    在此显式转换并校验，避免把弱类型一路下沉到 SQL 靠驱动隐式转换。
    """
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid {field}") from exc


async def _resolve_provider(
    db: AsyncSession,
    user_id: str,
    capability: str,
    *,
    config_id: Optional[str] = None,
    override_model: Optional[str] = None,
) -> BaseProvider:
    """按用户解析指定能力的 Provider，未命中（含系统兜底）→ 404。

    统一走 :func:`aresolve_user_model`（``/llm`` 路由保留系统兜底）：config_id 指定优先，
    否则取用户该能力默认配置，仍无则系统环境兜底；都没有抛 ``UserModelConfigMissingError``
    在此翻成 404，保持原有对外行为。``user_id`` / ``config_id`` 在边界归一成 int。
    """
    uid = _coerce_int(user_id, "X-User-Id")
    cid = _coerce_int(config_id, "config_id") if config_id is not None else None
    try:
        resolved = await aresolve_user_model(
            user_id=uid,
            capability=capability,
            config_id=cid,
            allow_system_fallback=True,
            override_model=override_model,
            db=db,
        )
    except UserModelConfigMissingError as exc:
        raise HTTPException(
            status_code=404, detail=f"{capability} configuration not found"
        ) from exc
    return resolved.provider


# ============ 请求模型 ============

class GenerateRequest(BaseModel):
    """生成文本请求"""
    config_id: Optional[str] = None
    prompt: str = Field(..., description="输入提示词")
    model: Optional[str] = Field(None, description="模型名称（覆盖配置）")
    temperature: float = Field(0.7, ge=0, le=2, description="采样温度")
    max_tokens: Optional[int] = Field(None, ge=1, description="最大 token 数")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    tools: Optional[List[dict]] = Field(None, description="工具调用定义")


class EmbedRequest(BaseModel):
    """向量化请求"""
    config_id: Optional[str] = None
    input: str | List[str] = Field(..., description="待向量化的文本")
    model: Optional[str] = Field(None, description="指定模型")


class RerankRequest(BaseModel):
    """重排请求"""
    config_id: Optional[str] = None
    query: str = Field(..., description="检索查询")
    documents: List[str] = Field(..., description="待重排的文档")
    model: Optional[str] = None
    top_n: Optional[int] = None


class OcrRequest(BaseModel):
    """OCR 请求"""
    config_id: Optional[str] = None
    image_base64: str = Field(..., description="图像 base64 编码")
    prompt: Optional[str] = Field(None, description="分析提示词")


# ============ 路由实现 ============

@router.post("/generate")
async def generate_text(
    request: GenerateRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """生成文本（非流式）

    Args:
        request: 生成请求参数
        x_user_id: 用户 ID
        db: 数据库 Session

    Returns:
        APIResponse[GenerateResult]
    """
    try:
        client = await _resolve_provider(
            db, x_user_id, "CHAT",
            config_id=request.config_id, override_model=request.model,
        )

        # 调用生成
        result = await client.generate(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        return APIResponse(
            code=200,
            message="success",
            data=result.model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            code=500,
            message=str(e),
            data=None,
        )


@router.post("/generate/stream")
async def generate_text_stream(
    request: GenerateRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
):
    """流式生成文本

    Returns:
        Server-Sent Events (SSE)
    """
    from fastapi.responses import StreamingResponse

    try:
        client = await _resolve_provider(
            db, x_user_id, "CHAT",
            config_id=request.config_id, override_model=request.model,
        )

        async def event_generator():
            async for chunk in client.stream(
                prompt=request.prompt,
                system_prompt=request.system_prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                yield f"data: {chunk.model_dump_json()}\n\n"
            yield "data: {\"is_end\": true}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(code=500, message=str(e), data=None)


@router.post("/embed")
async def embed_text(
    request: EmbedRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """文本向量化

    Returns:
        APIResponse[EmbeddingResult]
    """
    try:
        client = await _resolve_provider(
            db, x_user_id, "EMBEDDING",
            config_id=request.config_id, override_model=request.model,
        )

        result = await client.embed(texts=request.input, model=request.model)

        return APIResponse(
            code=200,
            message="success",
            data=result.model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(code=500, message=str(e), data=None)


@router.post("/rerank")
async def rerank_documents(
    request: RerankRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """语义重排

    Returns:
        APIResponse[RerankResult]
    """
    try:
        client = await _resolve_provider(
            db, x_user_id, "RERANK",
            config_id=request.config_id, override_model=request.model,
        )

        result = await client.rerank(
            query=request.query,
            documents=request.documents,
            model=request.model,
            top_n=request.top_n,
        )

        return APIResponse(
            code=200,
            message="success",
            data=result.model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(code=500, message=str(e), data=None)


@router.post("/ocr")
async def extract_text_from_image(
    request: OcrRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """OCR 图像文本提取

    Returns:
        APIResponse[dict]
    """
    try:
        client = await _resolve_provider(
            db, x_user_id, "OCR", config_id=request.config_id,
        )

        result = await client.extract_text(
            image_base64=request.image_base64,
            prompt=request.prompt,
        )

        return APIResponse(
            code=200,
            message="success",
            data=result.model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(code=500, message=str(e), data=None)