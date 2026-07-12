"""Manticore BM25 存储层异常。"""

from __future__ import annotations


class ManticoreStoreError(Exception):
    """Manticore 读写失败（连接失败、SQL 执行报错等服务级问题）。"""


class ManticoreConfigurationError(Exception):
    """缺少必要依赖（aiomysql）或配置非法。"""
