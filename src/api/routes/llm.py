"""
LLM API 路由
提供 LLM 调用接口：文本生成、向量化、重排等
"""
from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.llm.response import APIResponse
from src.services.config_reader_service import ConfigReaderService
from src.core.llm.factory import ModelFactory
from src.database import get_db

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])

# 依赖注入
model_factory = ModelFactory()


async def _resolve_config(
    config_service: ConfigReaderService,
    user_id: str,
    capability: str,
    config_id: Optional[str] = None,
) -> dict:
    """按当前接口能力解析可用配置。"""
    capability_upper = capability.upper()
    if config_id:
        config = await config_service.get_user_config_by_id(user_id, config_id)
        if config is None:
            raise HTTPException(
                status_code=404,
                detail=f"LLM {capability_upper} configuration not found",
            )
    else:
        config = await config_service.get_user_default_config_by_capability(
            user_id,
            capability_upper,
        )
        if config is None:
            raise HTTPException(
                status_code=404,
                detail=f"LLM {capability_upper} configuration not found",
            )

    config_capability = str(config.get("capability") or "").upper()
    if config_capability != capability_upper:
        raise HTTPException(
            status_code=400,
            detail=f"Config capability mismatch: expected {capability_upper}",
        )

    if not config.get("model_name"):
        raise HTTPException(
            status_code=400,
            detail="LLM configuration model_name is empty",
        )

    if not config.get("api_key"):
        raise HTTPException(
            status_code=400,
            detail="LLM configuration api_key is empty",
        )

    return config


async def _create_client_from_config(
    config_service: ConfigReaderService,
    config: dict,
    model_override: Optional[str] = None,
):
    """解密配置并创建 Provider client。"""
    try:
        api_key = await config_service.decrypt_api_key(config.get("api_key", ""))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="LLM configuration api_key decrypt failed",
        ) from exc

    return model_factory.create_client(
        provider_type=config.get("provider_type", "openai"),
        api_key=api_key,
        api_base_url=config.get("custom_api_base_url"),
        model_name=model_override or config.get("model_name"),
    )


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
        config_service = ConfigReaderService(db)
        config = await _resolve_config(
            config_service,
            x_user_id,
            "CHAT",
            request.config_id,
        )
        client = await _create_client_from_config(config_service, config, request.model)

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
        config_service = ConfigReaderService(db)
        config = await _resolve_config(
            config_service,
            x_user_id,
            "CHAT",
            request.config_id,
        )
        client = await _create_client_from_config(config_service, config, request.model)

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
        config_service = ConfigReaderService(db)
        config = await _resolve_config(
            config_service,
            x_user_id,
            "EMBEDDING",
            request.config_id,
        )
        client = await _create_client_from_config(config_service, config, request.model)

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
        config_service = ConfigReaderService(db)
        config = await _resolve_config(
            config_service,
            x_user_id,
            "RERANK",
            request.config_id,
        )
        client = await _create_client_from_config(config_service, config, request.model)

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
        config_service = ConfigReaderService(db)
        config = await _resolve_config(
            config_service,
            x_user_id,
            "OCR",
            request.config_id,
        )
        client = await _create_client_from_config(config_service, config)

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
