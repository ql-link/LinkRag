"""
LLM API 路由
提供 LLM 调用接口：文本生成、向量化、重排等
"""
from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.llm.response import (
    APIResponse,
    GenerateResult,
    EmbeddingResult,
    RerankResult,
    StreamChunk,
    UsageInfo,
)
from src.services.config_reader_service import ConfigReaderService
from src.core.llm.factory import ModelFactory
from src.database import get_db

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])

# 依赖注入
model_factory = ModelFactory()


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

        # 获取用户配置
        if request.config_id:
            config = await config_service.get_user_config_by_id(x_user_id, request.config_id)
        else:
            config = await config_service.get_user_default_config_by_capability(x_user_id, "CHAT")

        if not config:
            config = config_service.get_system_fallback_config_by_capability("CHAT")

        if not config:
            raise HTTPException(status_code=404, detail="LLM CHAT configuration not found")

        # 获取 Provider
        provider_type = config.get("provider_type", "openai")
        if config.get("is_system_fallback"):
            api_key = config.get("api_key", "")
        else:
            api_key = await config_service.decrypt_api_key(config.get("api_key", ""))

        client = model_factory.create_client(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=config.get("custom_api_base_url"),
            model_name=request.model or config.get("model_name"),
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
        config_service = ConfigReaderService(db)

        if request.config_id:
            config = await config_service.get_user_config_by_id(x_user_id, request.config_id)
        else:
            config = await config_service.get_user_default_config_by_capability(x_user_id, "CHAT")

        if not config:
            config = config_service.get_system_fallback_config_by_capability("CHAT")

        if not config:
            raise HTTPException(status_code=404, detail="LLM CHAT configuration not found")

        provider_type = config.get("provider_type", "openai")
        if config.get("is_system_fallback"):
            api_key = config.get("api_key", "")
        else:
            api_key = await config_service.decrypt_api_key(config.get("api_key", ""))

        client = model_factory.create_client(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=config.get("custom_api_base_url"),
            model_name=request.model or config.get("model_name"),
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
        config_service = ConfigReaderService(db)

        if request.config_id:
            config = await config_service.get_user_config_by_id(x_user_id, request.config_id)
        else:
            config = await config_service.get_user_default_config_by_capability(x_user_id, "EMBEDDING")

        if not config:
            config = config_service.get_system_fallback_config_by_capability("EMBEDDING")

        if not config:
            raise HTTPException(status_code=404, detail="Embedding configuration not found")

        provider_type = config.get("provider_type", "openai")
        if config.get("is_system_fallback"):
            api_key = config.get("api_key", "")
        else:
            api_key = await config_service.decrypt_api_key(config.get("api_key", ""))

        client = model_factory.create_client(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=config.get("custom_api_base_url"),
            model_name=request.model or config.get("model_name"),
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
        config_service = ConfigReaderService(db)

        if request.config_id:
            config = await config_service.get_user_config_by_id(x_user_id, request.config_id)
        else:
            config = await config_service.get_user_default_config_by_capability(x_user_id, "RERANK")

        if not config:
            config = config_service.get_system_fallback_config_by_capability("RERANK")

        if not config:
            raise HTTPException(status_code=404, detail="Rerank configuration not found")

        provider_type = config.get("provider_type", "openai")
        if config.get("is_system_fallback"):
            api_key = config.get("api_key", "")
        else:
            api_key = await config_service.decrypt_api_key(config.get("api_key", ""))

        client = model_factory.create_client(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=config.get("custom_api_base_url"),
            model_name=request.model or config.get("model_name"),
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
        config_service = ConfigReaderService(db)

        if request.config_id:
            config = await config_service.get_user_config_by_id(x_user_id, request.config_id)
        else:
            config = await config_service.get_user_default_config_by_capability(x_user_id, "OCR")

        if not config:
            config = config_service.get_system_fallback_config_by_capability("OCR")

        if not config:
            raise HTTPException(status_code=404, detail="OCR configuration not found")

        provider_type = config.get("provider_type", "openai")
        if config.get("is_system_fallback"):
            api_key = config.get("api_key", "")
        else:
            api_key = await config_service.decrypt_api_key(config.get("api_key", ""))

        client = model_factory.create_client(
            provider_type=provider_type,
            api_key=api_key,
            api_base_url=config.get("custom_api_base_url"),
            model_name=request.model or config.get("model_name"),
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