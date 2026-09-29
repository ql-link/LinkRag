"""Read Java's shared upload snapshot through the existing Python Redis client."""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.cache.redis_client import redis_client
from src.config import settings
from src.observability.audit import audit_event

_DEFAULT_SUFFIX_ORDER = ("md", "markdown", "pdf", "docx", "html", "htm")
_SUPPORTED = frozenset(_DEFAULT_SUFFIX_ORDER)
_KEY = "runtime:document-file:upload-config"


@dataclass(frozen=True)
class DocumentUploadLimits:
    allowed_suffixes: frozenset[str] = _SUPPORTED
    max_size_bytes: int = 20 * 1024 * 1024


_last_valid = DocumentUploadLimits()


async def current_limits() -> DocumentUploadLimits:
    """Shared Redis value wins; outages use the last valid snapshot or defaults."""
    global _last_valid
    try:
        raw = await redis_client.get(_KEY)
        if not raw:
            return _last_valid
        value = json.loads(raw)
        suffixes = value.get("allowedSuffixes") or value.get("allowed_suffixes")
        limit = value.get("maxSizeBytes") or value.get("max_size_bytes")
        allowed = frozenset(str(item).strip().lower() for item in suffixes)
        if (
            not allowed
            or not allowed.issubset(_SUPPORTED)
            or not 0 < int(limit) <= 100 * 1024 * 1024
        ):
            raise ValueError("invalid shared upload snapshot")
        _last_valid = DocumentUploadLimits(allowed, int(limit))
        return _last_valid
    except Exception:
        audit_event("DOCUMENT_UPLOAD_CONFIG_FALLBACK", "failed")
        return _last_valid


async def capabilities() -> dict:
    limits = await current_limits()
    return {
        "featureEnabled": settings.B5_FILE_WRITES_ENABLED,
        "document": {
            "allowedSuffixes": sorted(limits.allowed_suffixes),
            "maxSizeBytes": limits.max_size_bytes,
        },
        "image": {
            "extensions": ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff"],
            "mimeTypes": [
                "image/jpeg",
                "image/png",
                "image/gif",
                "image/webp",
                "image/bmp",
                "image/tiff",
            ],
            "maxAssetBytes": 20 * 1024 * 1024,
            "maxAssetCount": 200,
            "maxInventoryCount": 5000,
            "maxBundleBytes": 80 * 1024 * 1024,
            "maxPathLength": 512,
            "maxDocumentPathLength": 255,
        },
        "zip": {
            "maxCompressedBytes": 100 * 1024 * 1024,
            "maxEntries": 5000,
            "maxExpandedBytes": 500 * 1024 * 1024,
            "maxRatio": 100,
            "maxDepth": 20,
        },
        "matchModes": ["FULL_PATH", "SHALLOW_BASENAME"] if settings.B5_FILE_WRITES_ENABLED else [],
    }
