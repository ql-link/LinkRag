# -*- coding: utf-8 -*-
"""
外部模型（VLM/LLM）集成模块

定义用于与外部模型交互的接口，及处理 ParseResult 中的多模态/表格元素融合逻辑。
"""

import re
import logging
from abc import ABC, abstractmethod
from typing import Dict, List

from .models import ParseResult, ElementType


class VisionClient(ABC):
    """
    视觉模型客户端基类
    
    预期使用方式：
    其他开发者应继承此基类，并在系统中注入其派生类的实例。
    派生类需实现从 MinIO 获取原图，并调用大语言视觉模型以获得图片描述。
    """

    @abstractmethod
    def describe_images(self, image_urls: List[str], source_file: str | None = None) -> Dict[str, str]:
        """
        批量获取图片描述
        
        Args:
            image_urls: 图片链接（或路径）列表
            source_file: 解析的原始来源文件名（上下文，帮助定位相对路径的本地 MinIO 存储资产等）
            
        Returns:
            映射字典，格式为 { image_url: "VLM 提取的详细文字描述" }
        """
        pass


class ImageDescriber:
    """
    图片描述集成器
    
    负责将来自 VisionClient 的图片摘要信息融回 Markdown 系统中：
    1. 收集文档中发现的图片链接，交予外部系统处理。
    2. 将返回的自然语言描述以 `[视觉描述: ...]` 的形式附加到现有的 Markdown 内容中。
    """

    def __init__(self, vision_client: VisionClient):
        self._vision_client = vision_client

    def process(self, parse_result: ParseResult) -> ParseResult:
        """
        向 ParseResult 的图片元素中注入 VLM 输出的内容
        
        Args:
            parse_result: 由 MarkdownParser 解析出的初始结果
            
        Returns:
            融入了图片视觉描述的新 ParseResult 对象（在原对象上就地修改）
        """
        if not parse_result.images:
            return parse_result

        # 去重，获取唯一下载/访问链接
        unique_urls = list({img.url for img in parse_result.images})

        # 调用外部开发者的视觉接口
        try:
            descriptions = self._vision_client.describe_images(unique_urls, parse_result.source_file)
        except Exception as e:
            logging.error(f"VisionClient 请求发生异常，跳过图片描述融合: {e}")
            return parse_result
            
        if not descriptions:
            return parse_result

        # 建立按行号索引的图像列表，某一行可能有多个不同的图像引用
        image_line_mapping = {}
        for img in parse_result.images:
            if img.line not in image_line_mapping:
                image_line_mapping[img.line] = []
            image_line_mapping[img.line].append(img.url)

        # 遍历注入到具体的 Element 中
        for element in parse_result.elements:
            if element.type == ElementType.IMAGE:
                # 独立存在的一整行图片，直接精确命中 metadata
                url = element.metadata.get("url", "")
                desc = descriptions.get(url, "")
                if url and desc:
                    element.content = f"{element.content}\n\n[视觉描述: {desc}]"

            elif element.type == ElementType.PARAGRAPH:
                # 基于坐标的极速匹配，摒弃低效且极容易出错的正则表达式
                # 扫描此段落涵盖的所有行号
                for line in range(element.start_line, element.end_line + 1):
                    if line in image_line_mapping:
                        for url in image_line_mapping[line]:
                            desc = descriptions.get(url)
                            if desc:
                                # 对于在中间混合的多模态图片，不再尝试插入到句中原位（避免破坏句式），
                                # 而是直接作为段落的补充总结追加在整个元素末尾。
                                element.content += f"\n\n[视觉描述: {desc}]"

        return parse_result


class TableClient(ABC):
    """
    大语言模型（LLM）表格客户端基类
    
    预期使用方式：
    派生类负责接收 Markdown 原生表格字符串，调用外部 LLM，
    最后返回表格的文字描述或总结结论。
    """

    @abstractmethod
    def describe_tables(self, tables: List[str], source_file: str | None = None) -> Dict[str, str]:
        """
        批量获取表格描述
        
        Args:
            tables: 原始的 Markdown 表格字符串列表
            source_file: 解析的原始来源文件名（作为大模型总结时附加提供的前置知识上下文依据）
            
        Returns:
            映射字典，格式为 { raw_table_str: "LLM 提取的表格总结" }
        """
        pass


class TableDescriber:
    """
    表格描述集成器
    
    负责将来自 TableClient 的表格描述融合回 Markdown 的扫描元素中，
    原样保留原有 Markdown 表格文本并在其后追加 `[表格总结: ...]`。
    """

    def __init__(self, table_client: TableClient):
        self._table_client = table_client

    def process(self, parse_result: ParseResult) -> ParseResult:
        """
        向 ParseResult 中的表格追加 LLM 输出描述
        """
        if not parse_result.tables:
            return parse_result

        # 去重，避免同样内容的表格重复消耗 LLM Token
        unique_tables = list({t.content for t in parse_result.tables})

        try:
            descriptions = self._table_client.describe_tables(unique_tables, parse_result.source_file)
        except Exception as e:
            logging.error(f"TableClient 请求发生异常，跳过表格描述融合: {e}")
            return parse_result
            
        if not descriptions:
            return parse_result

        for element in parse_result.elements:
            # 表格已被 Scanner 原生识别为 TABLE 元素
            if element.type == ElementType.TABLE:
                desc = descriptions.get(element.content)
                if desc:
                    # 极其简单暴力的内容末端注射
                    element.content += f"\n\n[表格总结: {desc}]"
                        
        return parse_result
