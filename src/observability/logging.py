import logging
import os
import re
import shutil
import socket
import sys
import traceback
from hashlib import sha256
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from loguru import logger

from src.config import settings
from src.observability.tracing import get_trace_id

# 控制台格式：带颜色，便于本地开发查看。带 {process}（PID），多 worker
# 共写 stdout 时可区分来源进程。
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>{process}</magenta> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# 需要显式接管的标准库 logger 前缀：这些库自带 handler 且默认 propagate=False，
# 不接管则它们的日志（含 uvicorn 访问日志、500 堆栈）不会进入 Loguru sink。
_INTERCEPT_LOGGER_PREFIXES = ("uvicorn", "gunicorn", "fastapi")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_HOSTNAME = socket.gethostname()
DEFAULT_LOG_VALUE_LIMIT = 1024
_URL_CREDENTIAL_RE = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<credentials>[^/@\s]+)@",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?P<key>
        api[_-]?key|password|passwd|secret|access[_-]?token|refresh[_-]?token|
        authorization|credential|signature
    )
    (?P<separator>\s*["']?\s*[:=]\s*["']?\s*)
    (?P<value>[^"',}\s]+)
    """
)


def _service_name() -> str:
    return settings.LOG_SERVICE_NAME.strip() or "tolink-rag"


def truncate_log_value(value: object, limit: int = DEFAULT_LOG_VALUE_LIMIT) -> str:
    """将外部错误文本限制为单行定长字符串，避免日志注入与超大响应撑爆 Loki。"""
    text = str(value)
    text = _URL_CREDENTIAL_RE.sub(r"\g<scheme><redacted>@", text)
    text = _BEARER_RE.sub("Bearer <redacted>", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group('key')}{match.group('separator')}<redacted>",
        text,
    )
    text = " ".join(text.split())
    if limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated,total_chars={len(text)})"


def sanitize_url_for_log(raw_url: object) -> str:
    """移除 URL 用户密码、query 与 fragment，仅保留安全定位信息。"""
    text = str(raw_url or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "<invalid-url>"
    if not parsed.scheme or not parsed.netloc:
        return truncate_log_value(parsed.path or text, 256)

    try:
        hostname = parsed.hostname or ""
        parsed_port = parsed.port
    except ValueError:
        return f"{parsed.scheme}://<invalid-host>{parsed.path}"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed_port}" if parsed_port is not None else ""
    username = "<redacted>@" if parsed.username is not None else ""
    netloc = f"{username}{hostname}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def fingerprint_log_value(value: object, *, length: int = 12) -> str:
    """为不宜明文记录的资源生成稳定短指纹。"""
    return sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()[:length]


def safe_exception_stack(error: BaseException, *, limit: int = 4096) -> str:
    """提取不含异常消息和源码变量值的调用栈，适合记录外部系统异常。"""
    frames = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []
    stack = " <- ".join(
        f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in frames
    )
    return truncate_log_value(stack, limit)


def _patch_log_record(record: dict[str, Any]) -> None:
    """Attach fields shared by JSON file logs and console logs."""
    extra = record["extra"]
    extra.setdefault("service", _service_name())
    extra.setdefault("host", _HOSTNAME)
    extra.setdefault("pid", os.getpid())
    extra.setdefault("trace_id", get_trace_id() or "")
    extra.setdefault("logger_name", record["name"])


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
        while frame is not None and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.bind(logger_name=record.name).opt(depth=depth, exception=record.exc_info).log(
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
    logger.configure(patcher=_patch_log_record)

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
        service = _service_name()
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
            serialize=True,
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

__all__ = [
    "logger",
    "setup_logger",
    "InterceptHandler",
    "truncate_log_value",
    "sanitize_url_for_log",
    "fingerprint_log_value",
    "safe_exception_stack",
]
