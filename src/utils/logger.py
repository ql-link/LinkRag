import logging
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

# 需要显式接管的标准库 logger 前缀：这些库自带 handler 且默认 propagate=False，
# 不接管则它们的日志（含 uvicorn 访问日志、500 堆栈）不会进入 Loguru sink。
_INTERCEPT_LOGGER_PREFIXES = ("uvicorn", "gunicorn", "fastapi")


class InterceptHandler(logging.Handler):
    """把标准库 logging 的记录转发到 Loguru。

    项目自身代码统一用 Loguru，但第三方库（uvicorn / SQLAlchemy / kafka /
    transformers 等）以及少数遗留模块仍走标准库 logging。装上本 handler 后，
    所有标准库日志都会被路由进 Loguru，运行时只剩一条输出管道、统一格式与落盘。
    """

    def emit(self, record: logging.LogRecord) -> None:
        # 把标准库级别名映射为 Loguru 级别；未知则退回数值级别。
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 回溯到真正发出日志的调用帧，保证记录里的 file:line 指向业务代码，
        # 而非 logging 内部实现（depth==0 时强制先前进一帧，再持续跳过 logging 自身帧）。
        frame, depth = logging.currentframe(), 0
        while frame is not None and (
            depth == 0 or frame.f_code.co_filename == logging.__file__
        ):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _setup_intercept() -> None:
    """将标准库 logging 全量桥接到 Loguru。"""
    # root 级别置 0：放行所有记录，真正的级别过滤交给 Loguru sink 的 LOG_LEVEL。
    # force=True 清掉既有 root handler（含 uvicorn 启动时装的默认 handler）。
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 显式接管自带 handler / propagate=False 的库 logger：清空其 handler、
    # 打开 propagate，让记录冒泡到 root 的 InterceptHandler。
    for name in list(logging.root.manager.loggerDict):
        if name.startswith(_INTERCEPT_LOGGER_PREFIXES):
            std_logger = logging.getLogger(name)
            std_logger.handlers = []
            std_logger.propagate = True


def setup_logger():
    """配置 Loguru 日志系统。

    - 始终输出到 stdout（容器 / 本地通用）。
    - LOG_FILE_ENABLED 开启时，额外按 Java 端约定落盘：

        logs/<YYYY-MM-DD>/tolink-service.log         当天全量（>= LOG_LEVEL）
        logs/<YYYY-MM-DD>/tolink-service-error.log   当天 ERROR 及以上

      文件名中的 {time} 由 Loguru 在「创建新文件」时求值，配合每天 0 点切分
      （rotation="00:00"），每天自然落入新的日期目录；保留 LOG_RETENTION_DAYS 天。
    - 通过 InterceptHandler 把标准库 logging（含 uvicorn / 第三方库 / 遗留模块）
      桥接进 Loguru，使运行时只有一条统一的日志管道。

    可重复调用（幂等）：basicConfig(force=True) 会替换既有配置。
    """
    logger.remove()

    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=_CONSOLE_FORMAT,
        colorize=True,
        backtrace=True,
        # 生产环境关闭变量值展开，避免异常堆栈泄露密钥 / PII。
        diagnose=False,
    )

    if settings.LOG_FILE_ENABLED:
        base = settings.LOG_DIR.rstrip("/")
        service = settings.LOG_SERVICE_NAME
        common = dict(
            rotation="00:00",
            retention=f"{settings.LOG_RETENTION_DAYS} days",
            encoding="utf-8",
            enqueue=True,  # 多进程 / 异步安全，避免写入竞争阻塞业务
            format=_FILE_FORMAT,
            backtrace=True,
            diagnose=False,
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

    # 桥接标准库 logging → Loguru（放在 sink 配置之后，确保桥接来的记录有去处）。
    _setup_intercept()


# 初始化日志
setup_logger()

# 导出 logger 供其他模块使用
__all__ = ["logger", "setup_logger", "InterceptHandler"]
