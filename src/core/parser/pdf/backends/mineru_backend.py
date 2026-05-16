"""MinerU 精准解析 API 后端：通过官方云服务实现高质量 PDF 解析。

核心优势：
- VLM + OCR 双引擎，109 种语言 OCR 识别
- 表格 → HTML，公式 → LaTeX
- 图片/图表解析与描述
- 跨页表格合并、多栏布局、扫描件/手写体支持

接口契约：
- 只支持 MinerU 官方 V4 云端 API。
- 本后端提交公网可访问文件 URL，轮询 task_id 结果并下载结果 ZIP。

时间复杂度 O(n)，n 为 PDF 页数，受限于远端服务处理速度。
"""

from __future__ import annotations

import io
import re
import time
from typing import Any

import httpx
from loguru import logger

from src.core.parser.pdf.base import BasePdfBackend
from src.core.parser.pdf.models import PdfBinaryAsset

_DEFAULT_TIMEOUT_SECONDS = 300  # 长文档解析可能需要较长时间
_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class MinerUBackend(BasePdfBackend):
    """通过 MinerU 官方云端 API 调用解析服务的后端。"""

    name = "mineru"

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__()
        self._api_url = (api_url or "").rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def parse(self, file_stream: bytes, options: Any = None) -> tuple[str, list[PdfBinaryAsset]]:
        if not self._api_url:
            self.metadata["mineru_backend_error"] = "MINERU_API_URL 未配置"
            logger.warning("[MinerU Cloud] API URL 未配置，跳过此后端")
            return "", []
        if not self._api_key:
            self.metadata["mineru_backend_error"] = (
                "MINERU_API_KEY 未配置，MinerU 后端仅支持官方云端 API"
            )
            logger.warning("[MinerU Cloud] API Key 未配置，跳过此后端")
            return "", []

        source_file_url = getattr(options, "source_file_url", None)
        if not source_file_url:
            self.metadata["mineru_backend_error"] = (
                "MinerU 精准解析 API 需要 source_file_url，且该 URL 必须能被 MinerU 云端访问"
            )
            logger.warning("[MinerU Cloud] source_file_url 未配置，无法调用精准解析 API")
            return "", []

        model_version = getattr(options, "mineru_model_version", "vlm") or "vlm"

        try:
            markdown, assets = self._call_cloud_api(source_file_url, model_version)
            return markdown, assets
        except httpx.TimeoutException:
            self.metadata["mineru_backend_error"] = "API 请求超时"
            logger.error(f"[MinerU Cloud] API 请求超时 (timeout={self._timeout}s)")
            return "", []
        except httpx.ConnectError as exc:
            self.metadata["mineru_backend_error"] = f"无法连接 API: {exc}"
            logger.error(f"[MinerU Cloud] 无法连接 MinerU API: {self._api_url}")
            return "", []
        except Exception as exc:
            self.metadata["mineru_backend_error"] = str(exc)
            logger.error(f"[MinerU Cloud] 解析异常: {exc}")
            return "", []

    def _call_cloud_api(
        self,
        source_file_url: str,
        model_version: str,
    ) -> tuple[str, list[PdfBinaryAsset]]:
        """调用 MinerU 官方 V4 精准解析接口。

        流程：
        1. POST /api/v4/extract/task 提交文件 URL 获取 task_id
        2. 轮询 GET /api/v4/extract/task/{task_id} 直到 state == done
        3. 下载 full_zip_url 并解压提取 Markdown
        """
        import zipfile

        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        task_url = self._build_task_url()

        with httpx.Client(timeout=self._timeout) as client:
            create_data = {
                "url": source_file_url,
                "model_version": model_version,
            }
            logger.info(f"[MinerU Cloud] 正在创建精准解析任务: {task_url}")
            create_resp = client.post(task_url, headers=headers, json=create_data)
            create_resp.raise_for_status()
            create_res = create_resp.json()

            if create_res.get("code") != 0:
                raise Exception(f"创建精准解析任务失败: {create_res.get('msg')}")

            task_id = create_res["data"]["task_id"]
            poll_url = f"{task_url}/{task_id}"
            poll_headers = {"Authorization": headers["Authorization"]}

            logger.info(f"[MinerU Cloud] 任务创建成功，开始轮询解析结果: task_id={task_id}")
            start_time = time.time()
            full_zip_url = None
            markdown_url = None
            poll_interval = 1.0

            while time.time() - start_time < self._timeout:
                poll_resp = client.get(poll_url, headers=poll_headers)
                poll_resp.raise_for_status()
                poll_res = poll_resp.json()

                if poll_res.get("code") != 0:
                    logger.warning(f"轮询警告: {poll_res.get('msg')}")
                    continue

                task_state = poll_res.get("data", {})
                state = task_state.get("state")

                if state == "done":
                    full_zip_url, markdown_url = self._extract_result_urls(task_state)
                    logger.info("[MinerU Cloud] 解析成功！")
                    break
                elif state == "failed":
                    raise Exception(f"云端解析失败: {task_state.get('err_msg')}")
                else:
                    progress = task_state.get("extract_progress", {})
                    logger.info(
                        f"[MinerU Cloud] 解析中 ({progress.get('extracted_pages', 0)}/{progress.get('total_pages', 0)})..."
                    )
                    remaining_time = self._timeout - (time.time() - start_time)
                    if remaining_time > 0:
                        time.sleep(min(poll_interval, remaining_time))
                        poll_interval = min(poll_interval * 1.5, 5.0)

            if not full_zip_url and not markdown_url:
                raise Exception(f"云端解析超时 ({self._timeout}s)")

            if markdown_url:
                markdown = self._download_markdown(client, markdown_url)
                self.metadata["mineru_api_status"] = 200
                self.metadata["mineru_task_id"] = task_id
                self.metadata["mineru_model_version"] = model_version
                self.metadata["mineru_download_mode"] = "markdown_url"
                return markdown, []

            # 4. 流式下载并解压 ZIP
            zip_bytes = self._download_zip(client, full_zip_url)

            markdown = ""
            assets = []

            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                # 寻找 markdown 文件
                md_files = [f for f in z.namelist() if f.endswith(".md")]
                if md_files:
                    markdown = z.read(md_files[0]).decode("utf-8")

                # MinerU 云端 API 目前把图片放在 images 目录下
                # 因为用户配置了 image_bucket 流程，所以我们把图片作为 PdfBinaryAsset 传出去
                img_files = [
                    f for f in z.namelist() if f.startswith("images/") and not f.endswith("/")
                ]
                logger.info(
                    "[MinerU Cloud] ZIP 解压结果: md_files={}, image_files={}",
                    len(md_files),
                    len(img_files),
                )
                for idx, img_path in enumerate(img_files, start=1):
                    img_bytes = z.read(img_path)
                    ext = img_path.split(".")[-1] if "." in img_path else "png"
                    assets.append(
                        PdfBinaryAsset(
                            kind="picture",
                            page_number=idx,  # 云端没有页码，暂用 idx
                            index=idx,
                            ext=ext,
                            content=img_bytes,
                            source_path=img_path,
                        )
                    )

            self.metadata["mineru_api_status"] = 200
            self.metadata["mineru_task_id"] = task_id
            self.metadata["mineru_model_version"] = model_version
            self.metadata["mineru_download_mode"] = "zip_stream"
            return markdown, assets

    def _build_task_url(self) -> str:
        """兼容域名、/api/v4 和完整 /api/v4/extract/task 三种配置。"""
        if self._api_url.endswith("/api/v4/extract/task"):
            return self._api_url
        if "/api/v4" in self._api_url:
            return self._api_url.split("/api/v4")[0] + "/api/v4/extract/task"
        return f"{self._api_url.rstrip('/')}/api/v4/extract/task"

    def _extract_result_urls(self, task_state: dict[str, Any]) -> tuple[str | None, str | None]:
        """兼容 MinerU 结果 URL 可能位于 data 或 extract_result 下的返回结构。"""
        result = task_state.get("extract_result")
        if not isinstance(result, dict):
            result = {}

        full_zip_url = task_state.get("full_zip_url") or result.get("full_zip_url")
        markdown_url = (
            task_state.get("full_md_url")
            or task_state.get("markdown_url")
            or task_state.get("md_url")
            or result.get("full_md_url")
            or result.get("markdown_url")
            or result.get("md_url")
        )
        return full_zip_url, markdown_url

    def _download_markdown(self, client: httpx.Client, markdown_url: str) -> str:
        """下载 MinerU 直接返回的 Markdown 链接，避免不必要的 ZIP 传输。"""
        logger.info("[MinerU Cloud] 正在下载 Markdown 结果...")
        started_at = time.monotonic()
        markdown_bytes = self._stream_download_bytes(client, markdown_url)
        elapsed = time.monotonic() - started_at
        self.metadata["mineru_markdown_download_bytes"] = len(markdown_bytes)
        self.metadata["mineru_markdown_download_seconds"] = round(elapsed, 3)
        logger.info(
            "[MinerU Cloud] Markdown 下载完成: "
            f"bytes={len(markdown_bytes)}, elapsed={elapsed:.2f}s"
        )
        return markdown_bytes.decode("utf-8")

    def _download_zip(self, client: httpx.Client, full_zip_url: str) -> bytes:
        """分块流式下载 ZIP，避免 httpx 一次性缓存整个响应后才进入解压阶段。"""
        logger.info("[MinerU Cloud] 正在流式下载结果 ZIP...")
        started_at = time.monotonic()
        zip_bytes = self._stream_download_bytes(client, full_zip_url)
        elapsed = time.monotonic() - started_at
        self.metadata["mineru_zip_download_bytes"] = len(zip_bytes)
        self.metadata["mineru_zip_download_seconds"] = round(elapsed, 3)
        logger.info(
            "[MinerU Cloud] ZIP 下载完成: " f"bytes={len(zip_bytes)}, elapsed={elapsed:.2f}s"
        )
        return zip_bytes

    @staticmethod
    def _stream_download_bytes(client: httpx.Client, url: str) -> bytes:
        chunks: list[bytes] = []
        with client.stream("GET", url) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                if chunk:
                    chunks.append(chunk)
        return b"".join(chunks)

    def _extract_markdown(self, result: dict) -> str:
        """从 MinerU 返回结构中提取 Markdown 文本。

        兼容的返回格式可能为:
        1. {"markdown": "...", ...}
        2. {"md_content": "...", ...}
        3. {"content_list": [...], ...} (JSON 结构化)
        """
        # 优先取 markdown 或 md_content 字段
        md = result.get("markdown") or result.get("md_content") or ""
        if md:
            return md

        # 如果返回的是 content_list 结构化数据，拼接为 Markdown
        content_list = result.get("content_list", [])
        if content_list:
            return self._content_list_to_markdown(content_list)

        # 兜底：尝试直接转字符串
        return str(result) if result else ""

    def _content_list_to_markdown(self, content_list: list[dict]) -> str:
        """将 MinerU 的 content_list 结构化输出转为 Markdown。

        content_list 中每个元素的 type 可能为:
        - text: 普通文本
        - table: HTML 表格
        - image: 图片引用
        - equation/formula: LaTeX 公式
        """
        parts: list[str] = []
        for item in content_list:
            item_type = item.get("type", "text")
            content = item.get("content", "") or item.get("text", "")

            if item_type == "text":
                parts.append(content)
            elif item_type == "table":
                # MinerU 表格以 HTML 输出，直接嵌入 Markdown
                parts.append(content)
            elif item_type == "image":
                img_path = item.get("img_path", "")
                img_caption = item.get("img_caption", "图片")
                if img_path:
                    parts.append(f"![{img_caption}]({img_path})")
                else:
                    parts.append(f"> [图片] {img_caption}")
            elif item_type in ("equation", "formula"):
                # 行内或独立公式
                if "\n" in content or len(content) > 80:
                    parts.append(f"$$\n{content}\n$$")
                else:
                    parts.append(f"${content}$")
            else:
                parts.append(content)

        return "\n\n".join(parts)

    def _extract_assets(self, result: dict) -> list[PdfBinaryAsset]:
        """从 MinerU API 返回中提取已生成的图片资产。

        MinerU 通常会把图片保存到本地目录或返回 Base64。
        这里提取 content_list 中的 image 类型项。
        由于 MinerU 云端结果通常已在 Markdown 中保留图片路径引用，
        无需单独收集二进制资产——图片引用保留在 Markdown 文本中即可。
        """
        # MinerU 云端模式下，图片以 URL/路径形式直接内联在 Markdown 中，
        # 不需要额外收集 PdfBinaryAsset。
        # 如果需要将图片上传到自有对象存储，应在 service.py 层通过正则匹配图片链接后处理。
        return []
