"""MinerU HTTP API 后端：通过调用独立部署的 mineru-api 服务实现高质量 PDF 解析。

核心优势：
- VLM + OCR 双引擎，109 种语言 OCR 识别
- 表格 → HTML，公式 → LaTeX
- 图片/图表解析与描述
- 跨页表格合并、多栏布局、扫描件/手写体支持

接口契约：
- mineru-api 提供 POST /file_parse (同步) 和 POST /tasks (异步)
- 本后端使用 POST /file_parse 同步接口

时间复杂度 O(n)，n 为 PDF 页数，受限于远端服务处理速度。
"""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from src.core.parser.pdf.base import BasePdfBackend
from src.core.parser.pdf.models import PdfBinaryAsset


_DEFAULT_TIMEOUT_SECONDS = 300  # 长文档解析可能需要较长时间
_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class MinerUBackend(BasePdfBackend):
    """通过 HTTP API 调用 mineru-api 服务的解析后端。"""

    name = "mineru"

    def __init__(
        self, 
        api_url: str | None = None, 
        api_key: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        super().__init__()
        self._api_url = (api_url or "").rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def parse(self, file_stream: bytes, options: Any = None) -> tuple[str, list[PdfBinaryAsset]]:
        if not self._api_url:
            self.metadata["mineru_backend_error"] = "MINERU_API_URL 未配置"
            logger.warning("[MinerU] API URL 未配置，跳过此后端")
            return "", []

        try:
            markdown, assets = self._call_api(file_stream)
            return markdown, assets
        except httpx.TimeoutException:
            self.metadata["mineru_backend_error"] = "API 请求超时"
            logger.error(f"[MinerU] API 请求超时 (timeout={self._timeout}s)")
            return "", []
        except httpx.ConnectError as exc:
            self.metadata["mineru_backend_error"] = f"无法连接 API: {exc}"
            logger.error(f"[MinerU] 无法连接 mineru-api: {self._api_url}")
            return "", []
        except Exception as exc:
            self.metadata["mineru_backend_error"] = str(exc)
            logger.error(f"[MinerU] 解析异常: {exc}")
            return "", []

    def _call_api(self, file_stream: bytes) -> tuple[str, list[PdfBinaryAsset]]:
        """根据配置自动判断走本地开源接口还是云端官方 V4 接口。"""
        # 如果配置了 API Key，且 URL 包含 mineru.net，则走 V4 官方云端逻辑
        if self._api_key and "mineru.net" in self._api_url:
            return self._call_cloud_api(file_stream)
            
        # 否则默认走本地开源版本的单步直传接口
        return self._call_local_api(file_stream)

    def _call_local_api(self, file_stream: bytes) -> tuple[str, list[PdfBinaryAsset]]:
        """调用本地开源 mineru-api 的 POST /file_parse 同步接口。"""
        # MinerU 云端 API 提供了 /api/v1/extract 接口或其他路径，如果使用官网接口，需要使用其实际开放平台路径
        # 若是官网推荐的本地镜像或开源版本，接口一般为 /file_parse 或 /extract
        url = f"{self._api_url}/file_parse"
        
        # 处理可能的文件提交路径差异（兼容云端与开源版）
        if "mineru.net" in self._api_url or "extract" in self._api_url:
             # 如果配置了特定的云端路径，可能需要调整上传的文件参数名 (此处默认兼容其官方开源版)
             pass
             
        files = {"file": ("document.pdf", io.BytesIO(file_stream), "application/pdf")}
        data = {"parse_method": "auto", "is_json_md_dump": "true"}
        
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, files=files, data=data, headers=headers)
            response.raise_for_status()

        result = response.json()
        markdown = self._extract_markdown(result)
        assets = self._extract_assets(result)

        self.metadata["mineru_api_status"] = response.status_code
        self.metadata["mineru_parse_method"] = result.get("parse_method", "unknown")
        logger.info(
            f"[MinerU] 本地解析完成, parse_method={result.get('parse_method')}, "
            f"markdown_length={len(markdown)}, assets_count={len(assets)}"
        )
        return markdown, assets

    def _call_cloud_api(self, file_stream: bytes) -> tuple[str, list[PdfBinaryAsset]]:
        """调用 MinerU 官方 V4 云端接口。
        
        流程：
        1. POST /api/v4/file-urls/batch 获取上传链接和 batch_id
        2. PUT 提交 file_stream 到获取到的 URL
        3. 轮询 GET /api/v4/extract-results/batch/{batch_id} 直到 state == done
        4. 下载 full_zip_url 并解压提取 Markdown
        """
        import time
        import zipfile
        
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }
        
        # 补全基础 URL，防止用户只配了主域名
        base_url = self._api_url
        if not base_url.endswith("/api/v4"):
             # 如果用户配了 /api/v4/extract/task，则向上取到 /api/v4
             if "/api/v4" in base_url:
                 base_url = base_url.split("/api/v4")[0] + "/api/v4"
             else:
                 base_url = base_url.rstrip("/") + "/api/v4"
        
        with httpx.Client(timeout=self._timeout) as client:
            # 1. 申请上传链接
            apply_url = f"{base_url}/file-urls/batch"
            apply_data = {
                "files": [{"name": "document.pdf", "data_id": "doc1"}],
                "model_version": "vlm"
            }
            logger.info(f"[MinerU Cloud] 正在申请上传链接: {apply_url}")
            apply_resp = client.post(apply_url, headers=headers, json=apply_data)
            apply_resp.raise_for_status()
            apply_res = apply_resp.json()
            
            if apply_res.get("code") != 0:
                raise Exception(f"申请上传链接失败: {apply_res.get('msg')}")
                
            batch_id = apply_res["data"]["batch_id"]
            upload_url = apply_res["data"]["file_urls"][0]
            
            # 2. 上传文件
            logger.info(f"[MinerU Cloud] 正在上传文件到 OSS... batch_id={batch_id}")
            upload_resp = client.put(upload_url, content=file_stream)
            upload_resp.raise_for_status()
            
            # 3. 轮询结果
            poll_url = f"{base_url}/extract-results/batch/{batch_id}"
            poll_headers = {"Authorization": headers["Authorization"]}
            
            logger.info("[MinerU Cloud] 文件上传完毕，开始轮询云端解析结果...")
            start_time = time.time()
            full_zip_url = None
            
            while time.time() - start_time < self._timeout:
                time.sleep(5)
                poll_resp = client.get(poll_url, headers=poll_headers)
                poll_resp.raise_for_status()
                poll_res = poll_resp.json()
                
                if poll_res.get("code") != 0:
                    logger.warning(f"轮询警告: {poll_res.get('msg')}")
                    continue
                    
                extract_result = poll_res["data"].get("extract_result", [])
                if not extract_result:
                    continue
                    
                file_state = extract_result[0]
                state = file_state.get("state")
                
                if state == "done":
                    full_zip_url = file_state.get("full_zip_url")
                    logger.info("[MinerU Cloud] 解析成功！")
                    break
                elif state == "failed":
                    raise Exception(f"云端解析失败: {file_state.get('err_msg')}")
                else:
                    progress = file_state.get("extract_progress", {})
                    logger.info(f"[MinerU Cloud] 解析中 ({progress.get('extracted_pages', 0)}/{progress.get('total_pages', 0)})...")
                    
            if not full_zip_url:
                raise Exception(f"云端解析超时 ({self._timeout}s)")
                
            # 4. 下载并解压 ZIP
            logger.info(f"[MinerU Cloud] 正在下载结果 ZIP...")
            zip_resp = client.get(full_zip_url)
            zip_resp.raise_for_status()
            
            markdown = ""
            assets = []
            
            with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
                # 寻找 markdown 文件
                md_files = [f for f in z.namelist() if f.endswith(".md")]
                if md_files:
                    markdown = z.read(md_files[0]).decode("utf-8")
                
                # MinerU 云端 API 目前把图片放在 images 目录下
                # 因为用户配置了 image_bucket 流程，所以我们把图片作为 PdfBinaryAsset 传出去
                img_files = [f for f in z.namelist() if f.startswith("images/") and not f.endswith("/")]
                for idx, img_path in enumerate(img_files, start=1):
                    img_bytes = z.read(img_path)
                    ext = img_path.split(".")[-1] if "." in img_path else "png"
                    assets.append(PdfBinaryAsset(
                        kind="picture",
                        page_number=idx, # 云端没有页码，暂用 idx
                        index=idx,
                        ext=ext,
                        content=img_bytes
                    ))
            
            self.metadata["mineru_api_status"] = 200
            return markdown, assets

    def _extract_markdown(self, result: dict) -> str:
        """从 mineru-api 返回结构中提取 Markdown 文本。

        mineru-api 的返回格式可能为:
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
        由于 MinerU 通过 HTTP API 调用，图片 URL 已在 Markdown 中以相对路径引用，
        无需单独收集二进制资产——图片引用保留在 Markdown 文本中即可。
        """
        # MinerU HTTP API 模式下，图片以 URL/路径形式直接内联在 Markdown 中，
        # 不需要额外收集 PdfBinaryAsset。
        # 如果需要将图片上传到自有对象存储，应在 service.py 层通过正则匹配图片链接后处理。
        return []
