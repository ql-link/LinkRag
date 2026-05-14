"""文件级 ES 入库阶段入口。"""

from .models import EsIndexingResult
from .pipeline import EsIndexingPipeline

__all__ = ["EsIndexingPipeline", "EsIndexingResult"]
