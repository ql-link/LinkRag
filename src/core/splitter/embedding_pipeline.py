# -*- coding: utf-8 -*-
"""Final chunk embedding pipeline with batching and cache support."""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any, MutableMapping

import httpx

from src.core.markdown_parser import ParseResult
from src.utils.logger import logger

from .models import EmbeddedChunk, EmbeddingPipelineStats

if TYPE_CHECKING:
    from src.core.llm.interfaces import IEmbedder

    from .chunking_engine import ChunkingEngine
    from .models import Chunk
else:
    IEmbedder = Any
    ChunkingEngine = Any
    Chunk = Any


class ChunkEmbeddingPipeline:
    """
        串联最终分片结果的向量化流程，负责批量 embedding、缓存复用和统计信息记录。

    Args:
        None.

    Returns:
        None.
    """

    def __init__(
        self,
        chunking_engine: ChunkingEngine,
        embedder: IEmbedder,
        embedding_model: str | None = None,
        batch_size: int = 32,
        embedding_cache: MutableMapping[str, list[float]] | None = None,
    ):
        """
            初始化最终 Chunk 向量化管线，并注入分片引擎、embedding 客户端和缓存配置。

        Args:
            chunking_engine: 负责生成最终 Chunk 的分片引擎。
            embedder: 负责向量化最终 Chunk 的 embedding 客户端。
            embedding_model: 可选的 embedding 模型名称。
            batch_size: 单次批量向量化的最大 Chunk 数。
            embedding_cache: 可选的外部缓存映射，用于复用已计算向量。

        Returns:
            None.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive.")

        self.chunking_engine = chunking_engine
        self.embedder = embedder
        self.embedding_model = embedding_model
        self.batch_size = batch_size
        self.embedding_cache = embedding_cache if embedding_cache is not None else {}
        self.last_stats = EmbeddingPipelineStats(embedding_model=embedding_model)

    def _cache_key(self, content: str) -> str:
        """
            基于模型名与 Chunk 文本生成稳定缓存键，避免不同模型之间缓存串用。

        Args:
            content: 用于生成向量的最终 Chunk 文本。

        Returns:
            str: 对应缓存项的哈希键。
        """
        payload = f"{self.embedding_model or ''}\0{content}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _build_embedded_chunk(
        self,
        chunk: Chunk,
        embedding: list[float],
        model_name: str | None,
        cached: bool,
    ) -> EmbeddedChunk:
        """
            将原始 Chunk 与向量结果封装为统一的 `EmbeddedChunk` 输出对象。

        Args:
            chunk: 已完成切分的最终 Chunk。
            embedding: 与该 Chunk 对应的向量结果。
            model_name: 实际使用的 embedding 模型名称。
            cached: 当前向量是否来自缓存。

        Returns:
            EmbeddedChunk: 封装后的最终输出对象。
        """
        return EmbeddedChunk(
            chunk=chunk,
            embedding=[float(value) for value in embedding],
            embedding_model=model_name,
            cached=cached,
        )

    async def _embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        """
            对最终 Chunk 列表执行带缓存感知的批量向量化，并记录本次运行统计信息。

        Args:
            chunks: 待向量化的最终 Chunk 列表。

        Returns:
            list[EmbeddedChunk]: 与输入顺序一致的向量化结果列表。
        """
        if not chunks:
            self.last_stats = EmbeddingPipelineStats(embedding_model=self.embedding_model)
            return []

        results: list[EmbeddedChunk | None] = [None] * len(chunks)
        pending_items: list[tuple[int, str, Chunk]] = []
        cache_hits = 0
        cache_misses = 0
        batch_count = 0
        resolved_model = self.embedding_model

        for index, chunk in enumerate(chunks):
            cache_key = self._cache_key(chunk.content)
            cached_vector = self.embedding_cache.get(cache_key)
            if cached_vector is not None:
                cache_hits += 1
                results[index] = self._build_embedded_chunk(
                    chunk=chunk,
                    embedding=cached_vector,
                    model_name=resolved_model,
                    cached=True,
                )
                continue

            cache_misses += 1
            pending_items.append((index, cache_key, chunk))

        for start in range(0, len(pending_items), self.batch_size):
            batch = pending_items[start : start + self.batch_size]
            batch_count += 1

            try:
                response = await self.embedder.embed(
                    texts=[chunk.content for _, _, chunk in batch],
                    model=self.embedding_model,
                )
            except httpx.HTTPStatusError as exc:
                # 提取完整响应 body，方便区分 batch size / token 长度 / 鉴权 / 模型名等不同 400 原因
                try:
                    body = exc.response.text
                except Exception:
                    body = "<unable to read response body>"
                logger.error(
                    "[ChunkEmbeddingPipeline] Embedding API request failed: "
                    "status={} url={} batch_index={} batch_size={} model={} body={}",
                    exc.response.status_code,
                    str(exc.request.url),
                    start,
                    len(batch),
                    self.embedding_model,
                    body,
                )
                raise
            resolved_model = getattr(response, "model", resolved_model)
            embeddings = getattr(response, "embeddings", None) or []
            if len(embeddings) != len(batch):
                raise ValueError(
                    f"Embedding batch size mismatch: got {len(embeddings)}, expected {len(batch)}."
                )

            for (index, cache_key, chunk), embedding in zip(batch, embeddings):
                vector = [float(value) for value in embedding]
                self.embedding_cache[cache_key] = vector
                results[index] = self._build_embedded_chunk(
                    chunk=chunk,
                    embedding=vector,
                    model_name=resolved_model,
                    cached=False,
                )

        self.last_stats = EmbeddingPipelineStats(
            total_chunks=len(chunks),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            batch_count=batch_count,
            embedding_model=resolved_model,
        )
        return [result for result in results if result is not None]

    def embed_chunks(
        self,
        chunks: list[Chunk],
    ) -> list[EmbeddedChunk]:
        """
            提供同步入口，直接对已生成的最终 Chunk 列表执行向量化。

        Args:
            chunks: 待向量化的最终 Chunk 列表。

        Returns:
            list[EmbeddedChunk]: 向量化完成的结果列表。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aembed_chunks(chunks))

        raise RuntimeError(
            "ChunkEmbeddingPipeline.embed_chunks() cannot run inside an active event loop. "
            "Use await pipeline.aembed_chunks(...)."
        )

    async def aembed_chunks(
        self,
        chunks: list[Chunk],
    ) -> list[EmbeddedChunk]:
        """
            提供异步入口，直接对已生成的最终 Chunk 列表执行向量化。

        Args:
            chunks: 待向量化的最终 Chunk 列表。

        Returns:
            list[EmbeddedChunk]: 向量化完成的结果列表。
        """
        return await self._embed_chunks(chunks)

    async def aembed_query(self, query: str) -> list[float]:
        """
        对单条 query 文本向量化，供召回路径（``VectorStorageFacade.search_dense_chunks``）使用。

        与 ``aembed_chunks`` 共用 ``self.embedder`` + ``self.embedding_model``，
        从代码层保证写入 / 召回向量空间不分叉（§4.4.1 假设）。**故意不走 cache**
        （query 几乎不重复，cache key 是 hash(model+content) 对 query 无意义），
        **故意不批量化**（query 是单条），**故意不更新 last_stats**（last_stats 是
        写入路径的统计字段，与 query 无关）。

        Args:
            query: 用户问题或关键词；空字符串或全空白抛 ``ValueError``。
                注意：召回侧"空 query 短路返空"由 facade 入口提前 return，正常
                路径下不会让空 query 走到本方法；这里的 ValueError 是防御性兜底。

        Returns:
            list[float]: 单条 query 的稠密向量（与 ``aembed_chunks`` 输出每条
            ``EmbeddedChunk.embedding`` 同维度、同空间）。

        Raises:
            ValueError: query 为空或全空白；或 embedder 返回向量数量不为 1。
            httpx.HTTPStatusError / httpx.TimeoutException / 其它: 由调用方
                （facade）翻译为 ``VectorRetrievalEncodingError``；本方法不吞异常。
        """
        if not query or not query.strip():
            raise ValueError("query must not be empty or whitespace")

        response = await self.embedder.embed(
            texts=[query.strip()],
            model=self.embedding_model,
        )
        embeddings = getattr(response, "embeddings", None) or []
        if len(embeddings) != 1:
            raise ValueError(
                f"Embedding API returned {len(embeddings)} vectors for single query, "
                f"expected 1."
            )
        return [float(value) for value in embeddings[0]]

    def process(
        self,
        text: str,
        source_file: str | None = None,
        **kwargs,
    ) -> list[EmbeddedChunk]:
        """
            提供同步全链路入口，对原始文本执行解析、分片与最终向量化。

        Args:
            text: 原始 Markdown 文本。
            source_file: 可选的来源文件名。
            **kwargs: 透传给 chunking 引擎的扩展配置。

        Returns:
            list[EmbeddedChunk]: 完整流程输出的向量化分片结果。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aprocess(text, source_file=source_file, **kwargs))

        raise RuntimeError(
            "ChunkEmbeddingPipeline.process() cannot run inside an active event loop. "
            "Use await pipeline.aprocess(...)."
        )

    async def aprocess(
        self,
        text: str,
        source_file: str | None = None,
        **kwargs,
    ) -> list[EmbeddedChunk]:
        """
            提供异步全链路入口，对原始文本执行解析、分片与最终向量化。

        Args:
            text: 原始 Markdown 文本。
            source_file: 可选的来源文件名。
            **kwargs: 透传给 chunking 引擎的扩展配置。

        Returns:
            list[EmbeddedChunk]: 完整流程输出的向量化分片结果。
        """
        chunks = await self.chunking_engine.aprocess(text, source_file=source_file, **kwargs)
        return await self._embed_chunks(chunks)

    def process_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[EmbeddedChunk]:
        """
            提供同步入口，直接消费已生成的 `ParseResult` 继续执行分片和最终向量化。

        Args:
            parse_result: 已完成解析的结构化结果对象。
            **kwargs: 透传给 chunking 引擎的扩展配置。

        Returns:
            list[EmbeddedChunk]: 向量化完成的分片结果。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aprocess_parse_result(parse_result, **kwargs))

        raise RuntimeError(
            "ChunkEmbeddingPipeline.process_parse_result() cannot run inside an active event loop. "
            "Use await pipeline.aprocess_parse_result(...)."
        )

    async def aprocess_parse_result(
        self,
        parse_result: ParseResult,
        **kwargs,
    ) -> list[EmbeddedChunk]:
        """
            提供异步入口，直接消费已生成的 `ParseResult` 继续执行分片和最终向量化。

        Args:
            parse_result: 已完成解析的结构化结果对象。
            **kwargs: 透传给 chunking 引擎的扩展配置。

        Returns:
            list[EmbeddedChunk]: 向量化完成的分片结果。
        """
        chunks = await self.chunking_engine.aprocess_parse_result(parse_result, **kwargs)
        return await self._embed_chunks(chunks)

    def process_file(
        self,
        filepath: str,
        encoding: str = "utf-8",
        **kwargs,
    ) -> list[EmbeddedChunk]:
        """
            提供同步全链路入口，从文件解析 Markdown、分片并完成最终向量化。

        Args:
            filepath: Markdown 文件路径。
            encoding: 文件编码，默认使用 `utf-8`。
            **kwargs: 透传给 chunking 引擎的扩展配置。

        Returns:
            list[EmbeddedChunk]: 向量化完成的分片结果。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aprocess_file(filepath, encoding=encoding, **kwargs))

        raise RuntimeError(
            "ChunkEmbeddingPipeline.process_file() cannot run inside an active event loop. "
            "Use await pipeline.aprocess_file(...)."
        )

    async def aprocess_file(
        self,
        filepath: str,
        encoding: str = "utf-8",
        **kwargs,
    ) -> list[EmbeddedChunk]:
        """
            提供异步全链路入口，从文件解析 Markdown、分片并完成最终向量化。

        Args:
            filepath: Markdown 文件路径。
            encoding: 文件编码，默认使用 `utf-8`。
            **kwargs: 透传给 chunking 引擎的扩展配置。

        Returns:
            list[EmbeddedChunk]: 向量化完成的分片结果。
        """
        chunks = await self.chunking_engine.aprocess_file(filepath, encoding=encoding, **kwargs)
        return await self._embed_chunks(chunks)
