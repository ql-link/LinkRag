import sys
from loguru import logger
from src.config import settings

def setup_logger():
    """配置 Loguru 日志系统"""
    # 移除默认处理器
    logger.remove()
    
    # 添加标准输出处理器
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True
    )
    
    # 可以在这里添加文件输出处理器
    # logger.add("logs/app.log", rotation="500 MB", level="INFO")

# 初始化日志
setup_logger()

# 导出 logger 供其他模块使用
__all__ = ["logger"]
