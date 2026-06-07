import sys

from loguru import logger

from src.config import settings

# 控制台格式：带颜色，便于本地开发查看
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# 文件格式：无颜色控制符，便于落盘与日志采集
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} - {message}"
)


def setup_logger():
    """配置 Loguru 日志系统。

    - 始终输出到 stdout（容器 / 本地通用）。
    - LOG_FILE_ENABLED 开启时，额外按 Java 端约定落盘：

        logs/<YYYY-MM-DD>/tolink-service.log         当天全量（>= LOG_LEVEL）
        logs/<YYYY-MM-DD>/tolink-service-error.log   当天 ERROR 及以上

      文件名中的 {time} 由 Loguru 在「创建新文件」时求值，配合每天 0 点切分
      （rotation="00:00"），每天自然落入新的日期目录；保留 LOG_RETENTION_DAYS 天。
    """
    logger.remove()

    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=_CONSOLE_FORMAT,
        colorize=True,
    )

    if not settings.LOG_FILE_ENABLED:
        return

    base = settings.LOG_DIR.rstrip("/")
    service = settings.LOG_SERVICE_NAME
    retention = f"{settings.LOG_RETENTION_DAYS} days"
    common = dict(
        rotation="00:00",
        retention=retention,
        encoding="utf-8",
        enqueue=True,  # 多进程 / 异步安全，避免写入竞争阻塞业务
        format=_FILE_FORMAT,
    )

    # 当天全量日志
    logger.add(
        base + "/{time:YYYY-MM-DD}/" + f"{service}.log",
        level=settings.LOG_LEVEL,
        **common,
    )

    # 当天 ERROR 日志（独立文件）
    logger.add(
        base + "/{time:YYYY-MM-DD}/" + f"{service}-error.log",
        level="ERROR",
        **common,
    )


# 初始化日志
setup_logger()

# 导出 logger 供其他模块使用
__all__ = ["logger"]
