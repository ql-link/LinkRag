"""B8 管理统计、运行配置和日志代理。"""

import asyncio
import hashlib
import json
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.management_http import BusinessError
from src.application import document_runtime_config as upload_config
from src.cache.redis_client import redis_client
from src.config import settings
from src.observability.audit import audit_event

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_LEVELS = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "ACCESS", "AUDIT"]
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_SENSITIVE = re.compile(
    r'(?i)("?(?:api[_-]?key|access[_-]?key(?:[_-]?id)?|secret[_-]?key|authorization|token|password|secret)"?\s*[:=]\s*"?)([^\s,"\'}]+)'
)
_FINGERPRINT_KEY = "runtime:document-file:default-fingerprint"


def _metric(current: int, previous: int) -> dict:
    return {
        "current": current,
        "previous": previous,
        "growthRate": (current - previous) / previous if previous else None,
    }


async def user_dashboard(db: AsyncSession, days: int) -> dict:
    if days not in {7, 30, 90}:
        raise BusinessError(20008, "用户统计范围仅支持7、30或90天", 400)
    today = datetime.now(_SHANGHAI).date()
    first = today - timedelta(days=days - 1)
    previous = first - timedelta(days=days)
    end = today + timedelta(days=1)
    breakdown = (await db.execute(text("""
        SELECT SUM(role='USER') AS user_count, SUM(role='ADMIN') AS admin_count,
               SUM(status=1) AS enabled_count, SUM(status<>1) AS disabled_count
        FROM sys_user
    """))).mappings().one()
    values = {
        "user": int(breakdown["user_count"] or 0),
        "admin": int(breakdown["admin_count"] or 0),
        "enabled": int(breakdown["enabled_count"] or 0),
        "disabled": int(breakdown["disabled_count"] or 0),
    }
    params = {
        "previous": datetime.combine(previous, time.min),
        "first": datetime.combine(first, time.min),
        "end": datetime.combine(end, time.min),
    }
    created = (
        (
            await db.execute(
                text("""
        SELECT DATE(created_at) AS day, COUNT(*) AS count FROM sys_user
        WHERE created_at >= :previous AND created_at < :end GROUP BY DATE(created_at)
    """),
                params,
            )
        )
        .mappings()
        .all()
    )
    active = (
        (
            await db.execute(
                text("""
        SELECT DATE(created_at) AS day, COUNT(DISTINCT user_id) AS count
        FROM user_login_event WHERE created_at >= :previous AND created_at < :end
        GROUP BY DATE(created_at)
    """),
                params,
            )
        )
        .mappings()
        .all()
    )
    created_map = {str(r["day"]): int(r["count"]) for r in created}
    active_map = {str(r["day"]): int(r["count"]) for r in active}
    current_new = sum(created_map.get(str(first + timedelta(days=i)), 0) for i in range(days))
    previous_new = sum(created_map.get(str(previous + timedelta(days=i)), 0) for i in range(days))
    # 每周期 distinct 用户数不能由逐日 distinct 相加。
    current_active = (
        await db.scalar(
            text("""
        SELECT COUNT(DISTINCT user_id) FROM user_login_event
        WHERE created_at >= :first AND created_at < :end
    """),
            params,
        )
        or 0
    )
    previous_active = (
        await db.scalar(
            text("""
        SELECT COUNT(DISTINCT user_id) FROM user_login_event
        WHERE created_at >= :previous AND created_at < :first
    """),
            params,
        )
        or 0
    )
    trend = [
        {
            "date": str(day),
            "newUsers": created_map.get(str(day), 0),
            "activeUsers": active_map.get(str(day), 0),
        }
        for day in (first + timedelta(days=i) for i in range(days))
    ]
    return {
        "rangeDays": days,
        "totalUsers": values["user"] + values["admin"],
        "breakdown": values,
        "newUsers": _metric(current_new, previous_new),
        "activeUsers": _metric(int(current_active), int(previous_active)),
        "trend": trend,
    }


async def get_upload_config() -> dict:
    limits = await upload_config.current_limits()
    metadata = {"updatedBy": None, "updatedAt": None}
    allowed_suffixes = [
        suffix
        for suffix in upload_config._DEFAULT_SUFFIX_ORDER
        if suffix in limits.allowed_suffixes
    ]
    allowed_suffixes.extend(sorted(limits.allowed_suffixes.difference(allowed_suffixes)))
    try:
        raw = await redis_client.get(upload_config._KEY)
        if raw:
            snapshot = json.loads(raw)
            snapshot_suffixes = [
                str(value).strip().lower() for value in snapshot.get("allowedSuffixes", [])
            ]
            if (
                int(snapshot.get("maxSizeBytes", 0)) == limits.max_size_bytes
                and frozenset(snapshot_suffixes) == limits.allowed_suffixes
                and len(snapshot_suffixes) == len(limits.allowed_suffixes)
            ):
                allowed_suffixes = snapshot_suffixes
                metadata = {
                    "updatedBy": snapshot.get("updatedBy"),
                    "updatedAt": snapshot.get("updatedAt"),
                }
    except Exception:
        pass
    return {"maxSizeBytes": limits.max_size_bytes, "allowedSuffixes": allowed_suffixes, **metadata}


async def update_upload_config(user_id: int, max_size_bytes: int, suffixes: list[str]) -> dict:
    normalized = list(dict.fromkeys(s.strip().lower() for s in suffixes if s.strip()))
    if (
        not 0 < max_size_bytes <= 100 * 1024 * 1024
        or not normalized
        or any(s not in upload_config._SUPPORTED for s in normalized)
    ):
        raise BusinessError(10010, "文档文件上传配置不合法", 400)
    defaults = {
        "maxSizeBytes": upload_config.DocumentUploadLimits().max_size_bytes,
        "hardMaxSizeBytes": 100 * 1024 * 1024,
        "allowedSuffixes": sorted(upload_config._SUPPORTED),
    }
    canonical = json.dumps(defaults, separators=(",", ":"), ensure_ascii=False).encode()
    fingerprint = hashlib.sha256(canonical).hexdigest()
    try:
        created = await redis_client.set_if_absent(_FINGERPRINT_KEY, json.dumps(fingerprint))
        if not created:
            existing = await redis_client.get(_FINGERPRINT_KEY)
            if existing is None or json.loads(existing) != fingerprint:
                raise BusinessError(50003, "实例上传默认配置不一致，暂不可修改", 503)
    except BusinessError:
        raise
    except Exception as exc:
        raise BusinessError(50003, "Redis 不可用，文档文件上传配置未更新", 503) from exc
    # 先验证 Redis 可写，失败时不修改当前进程快照。
    snapshot = {
        "maxSizeBytes": max_size_bytes,
        "allowedSuffixes": normalized,
        "updatedBy": user_id,
        "updatedAt": datetime.now(_SHANGHAI).replace(tzinfo=None).isoformat(),
    }
    try:
        if not await redis_client.set(upload_config._KEY, json.dumps(snapshot, ensure_ascii=False)):
            raise RuntimeError("redis SET returned false")
    except Exception as exc:
        raise BusinessError(50003, "Redis 写入失败，旧配置继续生效", 503) from exc
    upload_config._last_valid = upload_config.DocumentUploadLimits(
        frozenset(normalized), max_size_bytes
    )
    audit_event("DOCUMENT_FILE_CONFIG_UPDATE", "success", actor_id=user_id)
    return snapshot


def _iso(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BusinessError(400, "时间必须是 ISO 格式", 400) from exc
    return (
        parsed.replace(tzinfo=_SHANGHAI).astimezone(timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def _redact(value: str | None) -> str | None:
    return _SENSITIVE.sub(r"\1******", value) if value is not None else None


def _entry(timestamp: str, line: str, labels: dict) -> dict:
    result = {
        "time": datetime.fromtimestamp(int(timestamp) / 1_000_000_000, timezone.utc).isoformat(),
        "level": labels.get("level"),
        "service": labels.get("service") or labels.get("service_name"),
        "host": labels.get("host"),
        "pid": None,
        "trace_id": None,
        "logger_name": None,
        "message": None,
        "exception": None,
    }
    try:
        data = json.loads(line)
        if "record" in data:
            record = data["record"]
            extra = record.get("extra") or {}
            record_time = record.get("time") or {}
            result.update(
                time=record_time.get("repr") or result["time"],
                level=(record.get("level") or {}).get("name"),
                service=extra.get("service") or result["service"],
                host=extra.get("host") or result["host"],
                pid=str(extra.get("pid") or (record.get("process") or {}).get("id") or "") or None,
                trace_id=extra.get("trace_id") or extra.get("traceId"),
                logger_name=extra.get("logger_name")
                or extra.get("loggerName")
                or record.get("name"),
                message=_redact(record.get("message")),
                exception=(
                    _redact(str(record.get("exception"))) if record.get("exception") else None
                ),
            )
        else:
            result.update(
                time=data.get("time") or data.get("@timestamp") or result["time"],
                level=data.get("level"),
                service=data.get("service") or result["service"],
                host=data.get("host") or result["host"],
                pid=data.get("pid"),
                trace_id=data.get("trace_id") or data.get("traceId"),
                logger_name=data.get("logger_name") or data.get("loggerName") or data.get("logger"),
                message=_redact(data.get("message")),
                exception=_redact(
                    data.get("exception") or data.get("stack_trace") or data.get("stackTrace")
                ),
            )
        if result["logger_name"] in {"ACCESS", "AUDIT"}:
            result["level"] = result["logger_name"]
    except (ValueError, TypeError, AttributeError):
        result["message"] = _redact(line)
        result["raw"] = _redact(line)
    return result


async def query_logs(
    service: str | None,
    level: str | None,
    trace_id: str | None,
    keyword: str | None,
    start_time: str | None,
    end_time: str | None,
    page: int,
    page_size: int,
) -> dict:
    page = min(max(page, 1), 1000)
    page_size = min(max(page_size, 1), 200)
    for name, value in (("service", service), ("trace_id", trace_id)):
        if value and not _IDENTIFIER.fullmatch(value):
            raise BusinessError(400, f"{name} 格式不合法", 400)
    if keyword and (len(keyword) > 200 or any(ord(c) < 32 for c in keyword)):
        raise BusinessError(400, "keyword 格式不合法", 400)
    level = level.upper() if level else None
    if level and level not in _LEVELS:
        raise BusinessError(400, "日志级别不合法", 400)
    end = _iso(end_time, datetime.now(timezone.utc))
    start = _iso(start_time, end - timedelta(hours=24))
    if start > end:
        raise BusinessError(400, "start_time 不能晚于 end_time", 400)

    def build_query(service_label: str) -> str:
        selectors = [f'{service_label}="{service}"' if service else f'{service_label}=~".+"']
        if level and level not in {"ACCESS", "AUDIT"}:
            selectors.append(f'level="{level}"')
        query = "{" + ", ".join(selectors) + "}"
        for value in ([f'"logger_name":"{level}"'] if level in {"ACCESS", "AUDIT"} else []) + [
            v for v in (trace_id, keyword) if v
        ]:
            query += " |= " + json.dumps(value)
        return query

    limit = min(page * page_size, 1000)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3)) as client:

            async def fetch(service_label: str) -> list:
                response = await client.get(
                    settings.LOKI_BASE_URL.rstrip("/") + "/loki/api/v1/query_range",
                    params={
                        "query": build_query(service_label),
                        "start": int(start.timestamp() * 1e9),
                        "end": int(end.timestamp() * 1e9),
                        "limit": limit,
                        "direction": "BACKWARD",
                    },
                )
                response.raise_for_status()
                return response.json()["data"]["result"]

            # Dev Promtail historically used service_name; newer streams use service.
            primary, legacy = await asyncio.gather(fetch("service"), fetch("service_name"))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise BusinessError(502, "日志服务暂不可用", 502) from exc
    values = (primary if isinstance(primary, list) else []) + (
        legacy if isinstance(legacy, list) else []
    )
    stamped = []
    seen = set()
    for result in values:
        if not isinstance(result, dict) or not isinstance(result.get("values"), list):
            continue
        labels = result.get("stream")
        if not isinstance(labels, dict):
            labels = {}
        for pair in result["values"]:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2 or not isinstance(pair[1], str):
                continue
            t, line = pair[0], pair[1]
            try:
                identity = (str(t), line, tuple(sorted(labels.items())))
                if identity in seen:
                    continue
                seen.add(identity)
                stamped.append((int(t), _entry(t, line, labels)))
            except (ValueError, TypeError, OverflowError):
                continue
    stamped.sort(key=lambda item: item[0], reverse=True)
    entries = [entry for _, entry in stamped]
    return {
        "items": entries[(page - 1) * page_size : page * page_size],
        "total": len(entries),
        "page": page,
        "pageSize": page_size,
        "totalPages": (len(entries) + page_size - 1) // page_size,
    }


async def log_labels() -> dict:
    services = ["tolink-service", "tolink-rag"]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3)) as client:

            async def labels(name: str) -> list:
                response = await client.get(
                    settings.LOKI_BASE_URL.rstrip("/") + f"/loki/api/v1/label/{name}/values"
                )
                response.raise_for_status()
                values = response.json().get("data", [])
                return values if isinstance(values, list) else []

            current, legacy = await asyncio.gather(labels("service"), labels("service_name"))
            values = current + legacy
            valid = sorted({s for s in values if isinstance(s, str) and _IDENTIFIER.fullmatch(s)})
            if valid:
                services = valid
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        pass
    return {"services": services, "levels": _LEVELS}
