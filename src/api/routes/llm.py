"""
LLM API 路由
提供 LLM 调用接口：文本生成、向量化、重排等
"""

from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.llm.response import APIResponse
from src.core.llm.base_provider import BaseProvider
from src.core.llm.exceptions import UserModelConfigMissingError
from src.core.llm.user_model_resolver import aresolve_user_model
from src.database import get_db

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])

# OCR 不是独立能力：图片文字提取 = VISION + 文字提取 prompt。/ocr 未带 prompt 时用此默认值。
_DEFAULT_OCR_PROMPT = (
    "请提取这张图片中的所有文字，按原始排版尽量还原；若图中无文字，则简要描述图片内容。"
)


def _sniff_image_media_type(image_base64: str) -> str:
    """从 base64 图片数据的 magic bytes 嗅探 MIME 类型，无法识别时回退 image/jpeg。

    /ocr 入参只有 base64、没有 mime 信息；据此推断后传给 VISION adapter 的 ``media_type``，
    避免一律写死 jpeg 导致 PNG/webp 在 Anthropic/Google 上因类型不符被拒。
    """
    import base64 as _base64

    try:
        head = _base64.b64decode(image_base64[:24])
    except Exception:
        return "image/jpeg"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


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


def _coerce_config_source(value: Optional[str]) -> str:
    """归一化配置来源，非法值 → 422。"""
    source = (value or "USER").upper()
    if source not in {"USER", "SYSTEM"}:
        raise HTTPException(status_code=422, detail="invalid config_source")
    return source


async def _resolve_provider(
    db: AsyncSession,
    user_id: str,
    capability: str,
    *,
    config_id: Optional[str] = None,
    config_source: Optional[str] = None,
    override_model: Optional[str] = None,
) -> BaseProvider:
    """按用户解析指定能力的 Provider，未命中 → 422。

    统一走 :func:`aresolve_user_model`：config_id 指定优先，否则取用户该能力默认配置。
    直调 ``/llm`` 路由不启用系统兜底，用户缺对应能力配置时直接返回明确错误。
    ``user_id`` / ``config_id`` 在边界归一成 int。
    """
    uid = _coerce_int(user_id, "X-User-Id")
    cid = _coerce_int(config_id, "config_id") if config_id is not None else None
    source = _coerce_config_source(config_source)
    try:
        resolved = await aresolve_user_model(
            user_id=uid,
            capability=capability,
            config_id=cid,
            config_source=source,
            allow_system_fallback=False,
            override_model=override_model,
            db=db,
        )
    except UserModelConfigMissingError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "LLM_CONFIG_MISSING",
                "message": (
                    f"user LLM config missing for capability {capability}; "
                    "please configure the model before calling this API"
                ),
                "capability": capability,
                "user_id": uid,
            },
        ) from exc
    return resolved.provider


# ============ 请求模型 ============


class GenerateRequest(BaseModel):
    """生成文本请求"""

    config_id: Optional[str] = None
    config_source: Optional[str] = Field("USER", description="配置来源：USER 或 SYSTEM")
    prompt: str = Field(..., description="输入提示词")
    model: Optional[str] = Field(None, description="模型名称（覆盖配置）")
    temperature: float = Field(0.7, ge=0, le=2, description="采样温度")
    max_tokens: Optional[int] = Field(None, ge=1, description="最大 token 数")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    tools: Optional[List[dict]] = Field(None, description="工具调用定义")


class EmbedRequest(BaseModel):
    """向量化请求"""

    config_id: Optional[str] = None
    config_source: Optional[str] = Field("USER", description="配置来源：USER 或 SYSTEM")
    input: str | List[str] = Field(..., description="待向量化的文本")
    model: Optional[str] = Field(None, description="指定模型")


class RerankRequest(BaseModel):
    """重排请求"""

    config_id: Optional[str] = None
    config_source: Optional[str] = Field("USER", description="配置来源：USER 或 SYSTEM")
    query: str = Field(..., description="检索查询")
    documents: List[str] = Field(..., description="待重排的文档")
    model: Optional[str] = None
    top_n: Optional[int] = None


class OcrRequest(BaseModel):
    """OCR 请求"""

    config_id: Optional[str] = None
    config_source: Optional[str] = Field("USER", description="配置来源：USER 或 SYSTEM")
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
            db,
            x_user_id,
            "CHAT",
            config_id=request.config_id,
            config_source=request.config_source,
            override_model=request.model,
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
        logger.exception(f"/llm/generate 调用失败 (user={x_user_id})")
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
            db,
            x_user_id,
            "CHAT",
            config_id=request.config_id,
            config_source=request.config_source,
            override_model=request.model,
        )

        async def event_generator():
            async for chunk in client.stream(
                prompt=request.prompt,
                system_prompt=request.system_prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                yield f"data: {chunk.model_dump_json()}\n\n"
            yield 'data: {"is_end": true}\n\n'

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"/llm 接口调用失败 (user={x_user_id})")
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
            db,
            x_user_id,
            "EMBEDDING",
            config_id=request.config_id,
            config_source=request.config_source,
            override_model=request.model,
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
        logger.exception(f"/llm 接口调用失败 (user={x_user_id})")
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
            db,
            x_user_id,
            "RERANK",
            config_id=request.config_id,
            config_source=request.config_source,
            override_model=request.model,
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
        logger.exception(f"/llm 接口调用失败 (user={x_user_id})")
        return APIResponse(code=500, message=str(e), data=None)


@router.post("/ocr")
async def extract_text_from_image(
    request: OcrRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """OCR 图像文本提取（兼容旧 endpoint）。

    OCR 不再是独立 LLM 能力：统一走 VISION（``analyze_image``）实现——读 VISION 配置、
    用文字提取 prompt、按嗅探到的真实 mime 传图。返回结构与原 OCR 一致（content/model/usage）。

    Returns:
        APIResponse[dict]
    """
    try:
        client = await _resolve_provider(
            db,
            x_user_id,
            "VISION",
            config_id=request.config_id,
            config_source=request.config_source,
        )

        result = await client.analyze_image(
            image_base64=request.image_base64,
            prompt=request.prompt or _DEFAULT_OCR_PROMPT,
            media_type=_sniff_image_media_type(request.image_base64),
        )

        return APIResponse(
            code=200,
            message="success",
            data=result.model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"/llm 接口调用失败 (user={x_user_id})")
        return APIResponse(code=500, message=str(e), data=None)
