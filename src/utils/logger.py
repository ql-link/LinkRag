import logging
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from src.config import settings

# 控制台格式：带颜色，便于本地开发查看。带 {process}（PID），多 worker
# 共写 stdout 时可区分来源进程。
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>{process}</magenta> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# 文件格式：无颜色控制符，便于落盘与日志采集。文件名已带 PID 隔离，行内不再重复进程号。
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} - {message}"
)

# 需要显式接管的标准库 logger 前缀：这些库自带 handler 且默认 propagate=False，
# 不接管则它们的日志（含 uvicorn 访问日志、500 堆栈）不会进入 Loguru sink。
_INTERCEPT_LOGGER_PREFIXES = ("uvicorn", "gunicorn", "fastapi")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


def _resolve_log_dir(raw_dir: str) -> Path:
    """Resolve LOG_DIR so relative values are stable across launch cwd."""
    normalized = (raw_dir.strip() or "logs").rstrip("/")
    path = Path(normalized).expanduser()
    if path.is_absolute():
        return path
    return _PROJECT_ROOT / path


def _cleanup_old_log_dirs(base: Path, retention_days: int) -> None:
    """按日期目录整体清理早于 retention_days 的旧日志（PID 无关、重启安全）。

    日志文件名带 PID，loguru 自带 retention 的清理 glob 会带上字面 PID，
    只能清掉「当前进程」写的文件；进程重启后 PID 变化，旧 PID 写的日期目录
    无人清理、会无限堆积，使 LOG_RETENTION_DAYS 形同虚设。这里改为按
    `<base>/<YYYY-MM-DD>/` 目录的日期整体清理，覆盖重启 / 多 worker / 崩溃残留。
    """
    if not base.is_dir():
        return
    cutoff = (datetime.now() - timedelta(days=retention_days)).date()
    for child in base.iterdir():
        if not child.is_dir():
            continue
        try:
            dir_date = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue  # 非日期目录，跳过（不误删用户其它内容）
        if dir_date < cutoff:
            shutil.rmtree(child, ignore_errors=True)


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
    - LOG_FILE_ENABLED 开启时，额外按 Java 端约定落盘（文件名带 PID 隔离多 worker）：

        logs/<YYYY-MM-DD>/<service>-<pid>.log         当天全量（>= LOG_LEVEL）
        logs/<YYYY-MM-DD>/<service>-error-<pid>.log   当天 ERROR 及以上

      文件名中的 {time} 由 Loguru 在「创建新文件」时求值，配合每天 0 点切分
      （rotation="00:00"），每天自然落入新的日期目录。保留清理见
      _cleanup_old_log_dirs：按日期目录整体删除早于 LOG_RETENTION_DAYS 的目录。
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
        # 空值回退默认；相对路径统一锚定项目根目录，避免从 src/ 等目录启动时
        # 生成第二份 src/logs。
        base = _resolve_log_dir(settings.LOG_DIR)
        service = settings.LOG_SERVICE_NAME.strip() or "tolink-service"
        # 文件名带 PID 隔离：多 worker（gunicorn）部署时各进程写各自文件，
        # 避免多进程共写同一文件导致的写入交错与 0 点切分/清理竞争。
        # 单进程部署也安全，仅文件名多一段 PID。
        # 注意：PID 在 setup_logger 调用时求值；gunicorn 若用 --preload，
        # 需在 post_fork 钩子里重新调用 setup_logger，否则各 worker 会复用 master 的 PID。
        pid = os.getpid()
        retention_days = settings.LOG_RETENTION_DAYS

        # 自定义 retention：忽略 loguru 按 PID 过滤的文件列表，改为按日期目录整体清理，
        # 使重启后旧 PID 的日志也能被回收。每天 0 点切分时触发（覆盖长跑进程跨天）。
        def _retention(_files):
            _cleanup_old_log_dirs(base, retention_days)

        # 启动时先扫一遍：进程刚拉起、尚未发生 rotation 时即回收上次运行残留的旧日期目录。
        _cleanup_old_log_dirs(base, retention_days)

        common = dict(
            rotation="00:00",
            retention=_retention,
            encoding="utf-8",
            enqueue=True,  # 多进程 / 异步安全，避免写入竞争阻塞业务
            format=_FILE_FORMAT,
            backtrace=True,
            diagnose=False,
        )

        # 当天全量日志
        logger.add(
            str(base / "{time:YYYY-MM-DD}" / f"{service}-{pid}.log"),
            level=settings.LOG_LEVEL,
            **common,
        )

        # 当天 ERROR 日志（独立文件）
        logger.add(
            str(base / "{time:YYYY-MM-DD}" / f"{service}-error-{pid}.log"),
            level="ERROR",
            **common,
        )

    # 桥接标准库 logging → Loguru（放在 sink 配置之后，确保桥接来的记录有去处）。
    _setup_intercept()


# 初始化日志
setup_logger()

# 导出 logger 供其他模块使用
__all__ = ["logger", "setup_logger", "InterceptHandler"]
