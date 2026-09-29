"""Java-compatible Markdown companion-image preflight and RAW bundle materialization."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from src.api.management_http import BusinessError

_IMAGE_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[/\\]")
_INLINE = re.compile(r"!\[((?:\\.|[^\]])*)\]\(((?:\\.|[^)])*)\)")
_REFERENCE = re.compile(r"!\[((?:\\.|[^\]])*)\]\[((?:\\.|[^\]])*)\]")
_DEFINITION = re.compile(r"(?m)^ {0,3}\[((?:\\.|[^\]])+)\]:\s*(.+)$")
_HTML = re.compile(r"<img\b[^>]*>", re.I | re.S)
_ATTR = r"\b{}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))"
_OBSIDIAN = re.compile(r"!\[\[((?:\\.|[^\]])+)\]\]")
_TITLE = re.compile(r"(?s)^(.*?)(?:\s+(\"[^\"]*\"|'[^']*'|\([^()]*\)))\s*$")


@dataclass(frozen=True)
class AssetFile:
    path: str
    original_filename: str
    temp_path: Path
    content_type: str | None
    size: int


@dataclass(frozen=True)
class Reference:
    syntax: str
    target: str
    alt: str
    start: int
    end: int


@dataclass(frozen=True)
class BundlePlan:
    document_path: str
    match_mode: str
    summary: dict
    markdown: str
    references: tuple[Reference, ...]
    matched: tuple[tuple[int, AssetFile], ...]
    validated: dict[str, tuple[str, str, str]]


@dataclass(frozen=True)
class BundleUpload:
    path: Path
    object_key: str
    content_type: str


def _error(code: int, message: str) -> BusinessError:
    return BusinessError(code, message, 400)


def _unescape(value: str) -> str:
    # Markdown escaping applies to punctuation; keep Windows separators so an
    # absolute drive path is still rejected by _local().
    return re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])", r"\1", value)


def _destination(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<"):
        end = value.find(">")
        return _unescape(value[1:end]) if end > 0 else ""
    title = _TITLE.fullmatch(value)
    return _unescape((title.group(1) if title else value).strip())


def _local(target: str) -> bool:
    value = target.strip()
    if not value:
        return False
    lower = value.lower()
    if (
        lower.startswith("file:")
        or value.startswith(("/", "\\\\"))
        or _WINDOWS_ABSOLUTE.match(value)
    ):
        raise _error(30011, "不支持本地绝对图片路径")
    if value.startswith(("#", "//")) or lower.startswith(("http:", "https:", "data:")):
        return False
    return not bool(_SCHEME.match(value))


def scan(markdown: str) -> tuple[Reference, ...]:
    # Reuse the existing plain-upload code-span exclusion policy.
    from src.application.document_uploads import _excluded_markdown_positions

    excluded = _excluded_markdown_positions(markdown)
    refs: list[Reference] = []
    definitions: dict[str, str] = {}
    for match in _DEFINITION.finditer(markdown):
        if not excluded[match.start()]:
            key = " ".join(_unescape(match.group(1)).split()).lower()
            definitions.setdefault(key, _destination(match.group(2)))
    for match in _INLINE.finditer(markdown):
        if not excluded[match.start()]:
            target = _destination(match.group(2))
            if _local(target):
                refs.append(Reference("MARKDOWN", target, _unescape(match.group(1)), *match.span()))
    for match in _REFERENCE.finditer(markdown):
        if not excluded[match.start()]:
            label = _unescape(match.group(2) or match.group(1))
            target = definitions.get(" ".join(label.split()).lower(), "")
            if _local(target):
                refs.append(
                    Reference(
                        "MARKDOWN_REFERENCE", target, _unescape(match.group(1)), *match.span()
                    )
                )
    for match in _HTML.finditer(markdown):
        if excluded[match.start()]:
            continue
        source = re.search(_ATTR.format("src"), match.group(), re.I | re.S)
        if source:
            target = html.unescape(
                next((value for value in source.groups() if value is not None), "")
            )
            if _local(target):
                alt = re.search(_ATTR.format("alt"), match.group(), re.I | re.S)
                alt_text = (
                    html.unescape(next((value for value in alt.groups() if value is not None), ""))
                    if alt
                    else ""
                )
                refs.append(Reference("HTML", target, alt_text, *match.span()))
    for match in _OBSIDIAN.finditer(markdown):
        if not excluded[match.start()]:
            parts = re.split(r"(?<!\\)\|", match.group(1), maxsplit=1)
            target = _unescape(parts[0]).strip()
            if _local(target):
                refs.append(
                    Reference(
                        "OBSIDIAN",
                        target,
                        _unescape(parts[1]).strip() if len(parts) > 1 else "",
                        *match.span(),
                    )
                )
    refs.sort(key=lambda item: item.start)
    output: list[Reference] = []
    end = -1
    for reference in refs:
        if reference.start >= end:
            output.append(reference)
            end = reference.end
    return tuple(output)


def catalog_path(raw: str | None) -> str:
    if not raw or not raw.strip():
        raise _error(400, "图片路径非法")
    value = unicodedata.normalize("NFC", raw.strip().replace("\\", "/"))
    if value.startswith("/") or _WINDOWS_ABSOLUTE.match(value) or _SCHEME.match(value):
        raise _error(400, "图片路径非法")
    parts = value.split("/")
    if any(
        not part or part in {".", ".."} or any(ord(ch) < 32 or ord(ch) == 127 for ch in part)
        for part in parts
    ):
        raise _error(400, "图片路径非法")
    return "/".join(parts)


def _variants(raw: str) -> tuple[str, ...]:
    value = unicodedata.normalize("NFC", raw.strip().replace("\\", "/"))
    if not value or value.startswith("/") or _WINDOWS_ABSOLUTE.match(value) or _SCHEME.match(value):
        raise _error(400, "图片路径非法")
    while value.startswith("./"):
        value = value[2:]
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise _error(400, "图片路径非法")
    result = [value]
    if "%" in value and not re.search(r"%(?![0-9A-Fa-f]{2})", value):
        try:
            decoded = unicodedata.normalize("NFC", unquote(value, errors="strict"))
            if decoded not in result:
                result.append(decoded)
        except UnicodeDecodeError:
            pass
    return tuple(result)


def _resolve(parent: str, target: str) -> str:
    if target.startswith("/") or _WINDOWS_ABSOLUTE.match(target) or _SCHEME.match(target):
        raise _error(30011, "不支持本地绝对图片路径")
    parts = parent.split("/") if parent else []
    for part in target.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise _error(30021, "图片路径越出上传根目录")
            parts.pop()
        elif any(ord(ch) < 32 or ord(ch) == 127 for ch in part):
            raise _error(400, "图片路径非法")
        else:
            parts.append(part)
    if not parts:
        raise _error(400, "图片路径非法")
    return "/".join(parts)


def _image_type(asset: AssetFile) -> tuple[str, str, str]:
    suffix = asset.path.rsplit(".", 1)[-1].lower()
    expected = _IMAGE_MIME.get(suffix)
    if not expected:
        raise _error(30014, "图片扩展名、MIME 与实际内容不一致")
    with asset.temp_path.open("rb") as source:
        prefix = source.read(16)
    if prefix.startswith(b"\xff\xd8\xff"):
        detected = ("jpg", "image/jpeg")
    elif prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = ("png", "image/png")
    elif prefix[:6] in {b"GIF87a", b"GIF89a"}:
        detected = ("gif", "image/gif")
    elif prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        detected = ("webp", "image/webp")
    elif prefix.startswith(b"BM"):
        detected = ("bmp", "image/bmp")
    elif prefix[:4] in {b"II*\x00", b"MM\x00*"}:
        detected = ("tiff", "image/tiff")
    else:
        detected = ("", "")
    declared = (asset.content_type or "").split(";", 1)[0].strip().lower()
    if detected[1] != expected or declared not in {"", "application/octet-stream", expected}:
        raise _error(30014, "图片扩展名、MIME 与实际内容不一致")
    with asset.temp_path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return detected[0], detected[1], digest


def preflight(
    markdown_path: Path,
    original_filename: str,
    match_mode: str | None,
    document_path: str | None,
    assets: list[AssetFile],
    inventory_paths: list[str],
) -> BundlePlan:
    if match_mode not in {"FULL_PATH", "SHALLOW_BASENAME"}:
        raise _error(30010, "Markdown 包含本地图片，请选择图片文件夹或确认缺图上传")
    if len(assets) > 200 or len(inventory_paths) > 5000:
        raise _error(30017, "图片数量超过限制")
    if markdown_path.stat().st_size + sum(asset.size for asset in assets) > 80 * 1024 * 1024:
        raise _error(30018, "Markdown 资源包总大小超过限制")
    name = catalog_path(original_filename)
    document = name if match_mode == "SHALLOW_BASENAME" else catalog_path(document_path)
    if len(document) > 255:
        raise _error(30019, "资源路径长度超过限制")
    paths: dict[str, AssetFile] = {}
    inventory: dict[str, None] = {}
    for raw in inventory_paths:
        path = catalog_path(raw)
        if len(path) > 512:
            raise _error(30019, "资源路径长度超过限制")
        if match_mode == "SHALLOW_BASENAME" and "/" in path:
            raise _error(400, "单文件补图只允许直接子级图片文件名")
        if path in inventory:
            raise _error(
                30012 if match_mode == "SHALLOW_BASENAME" else 30013,
                (
                    "图片文件名规范化后发生冲突"
                    if match_mode == "SHALLOW_BASENAME"
                    else "资源路径规范化后发生冲突"
                ),
            )
        inventory[path] = None
    for asset in assets:
        path = catalog_path(asset.path)
        if len(path) > 512:
            raise _error(30019, "资源路径长度超过限制")
        if match_mode == "SHALLOW_BASENAME" and "/" in path:
            raise _error(400, "单文件补图只允许直接子级图片文件名")
        if path in paths:
            raise _error(
                30012 if match_mode == "SHALLOW_BASENAME" else 30013,
                (
                    "图片文件名规范化后发生冲突"
                    if match_mode == "SHALLOW_BASENAME"
                    else "资源路径规范化后发生冲突"
                ),
            )
        paths[path] = AssetFile(
            path, path.rsplit("/", 1)[-1], asset.temp_path, asset.content_type, asset.size
        )
        inventory[path] = None
    try:
        markdown = markdown_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _error(400, "Markdown 文件必须使用 UTF-8 编码") from exc
    references = scan(markdown)
    summary: dict[str, Any] = {
        "matchMode": match_mode,
        "outcome": "READY",
        "matchedCount": 0,
        "missingCount": 0,
        "ambiguousCount": 0,
        "unsupportedCount": 0,
        "blockingIssues": False,
        "missingPaths": [],
        "candidateFilenames": [],
        "issues": [],
    }
    matched: list[tuple[int, AssetFile]] = []
    validated: dict[str, tuple[str, str, str]] = {}
    parent = document.rsplit("/", 1)[0] if "/" in document else ""
    for index, reference in enumerate(references):
        variants = _variants(reference.target)
        candidates: list[str] = []
        for variant in variants:
            if match_mode == "SHALLOW_BASENAME":
                candidate = variant.rsplit("/", 1)[-1]
                if candidate not in candidates:
                    candidates.append(candidate)
            else:
                for base in (parent, "") if reference.syntax == "OBSIDIAN" else (parent,):
                    candidate = _resolve(base, variant)
                    if candidate not in candidates:
                        candidates.append(candidate)
        if (
            match_mode == "FULL_PATH"
            and reference.syntax == "OBSIDIAN"
            and all("/" not in variant for variant in variants)
        ):
            basenames = {variant.rsplit("/", 1)[-1] for variant in variants}
            for path in inventory:
                if path.rsplit("/", 1)[-1] in basenames and path not in candidates:
                    candidates.append(path)
        existing = [candidate for candidate in candidates if candidate in inventory]
        chosen = existing[0] if len(existing) == 1 else (candidates[0] if candidates else "")
        status = (
            "AMBIGUOUS"
            if len(existing) > 1
            else (
                "MISSING"
                if not existing
                else (
                    "UNSUPPORTED"
                    if chosen.rsplit(".", 1)[-1].lower() not in _IMAGE_MIME
                    else "MISSING" if chosen not in paths else "MATCHED"
                )
            )
        )
        issue = {
            "syntax": reference.syntax,
            "originalTarget": reference.target,
            "normalizedTarget": chosen,
            "resolution": status,
            "issueKind": None,
            "originalFilename": None,
            "storedFilename": None,
            "logicalUri": None,
            "basenameCandidates": candidates,
            "candidateFilenames": existing,
        }
        summary[status.lower() + "Count"] += 1
        if status == "MATCHED":
            asset = paths[chosen]
            if asset.path not in validated:
                validated[asset.path] = _image_type(asset)
            issue["originalFilename"] = asset.original_filename
            matched.append((index, asset))
        elif status == "MISSING":
            issue["issueKind"] = "ASSET_MISSING"
            if chosen not in summary["missingPaths"]:
                summary["missingPaths"].append(chosen)
        elif status == "AMBIGUOUS":
            issue["issueKind"] = "ASSET_AMBIGUOUS"
            for candidate in existing:
                if candidate not in summary["candidateFilenames"]:
                    summary["candidateFilenames"].append(candidate)
        else:
            issue["issueKind"] = "UNSUPPORTED_IMAGE_TYPE"
            issue["originalFilename"] = chosen.rsplit("/", 1)[-1]
        summary["issues"].append(issue)
    for status, outcome in (
        ("ambiguousCount", "ASSET_AMBIGUOUS"),
        ("unsupportedCount", "UNSUPPORTED_IMAGE_TYPE"),
        ("missingCount", "ASSET_MISSING"),
    ):
        if summary[status]:
            summary["outcome"] = outcome
            break
    summary["blockingIssues"] = summary["outcome"] != "READY"
    return BundlePlan(
        document, match_mode, summary, markdown, references, tuple(matched), validated
    )


def materialize(
    plan: BundlePlan,
    original_path: Path,
    *,
    user_id: int,
    dataset_id: int,
    file_id: int,
    directory: Path,
) -> tuple[str, tuple[BundleUpload, ...], tuple[Path, ...]]:
    prefix = f"markdown-assets/v1/user-{user_id}/dataset-{dataset_id}/file-{file_id}/"
    original_key, normalized_key = prefix + "source/original.md", prefix + "source/normalized.md"
    image_entries: dict[str, dict] = {}
    image_uploads: dict[str, BundleUpload] = {}
    replacements: list[tuple[int, int, str]] = []
    for index, asset in plan.matched:
        extension, mime, digest = plan.validated[asset.path]
        filename = f"image-{digest}.{extension}"
        key = prefix + "images/" + filename
        uri = "tolink-raw://raw/" + key
        issue = plan.summary["issues"][index]
        issue["storedFilename"] = filename
        issue["logicalUri"] = uri
        image_entries.setdefault(
            filename,
            {
                "originalFilename": asset.original_filename,
                "normalizedPath": asset.path,
                "storedFilename": filename,
                "objectKey": key,
                "sha256": digest,
                "mimeType": mime,
                "sizeBytes": asset.size,
            },
        )
        image_uploads.setdefault(filename, BundleUpload(asset.temp_path, key, mime))
        reference = plan.references[index]
        alt = reference.alt.replace("\\", "\\\\").replace("]", "\\]")
        replacements.append((reference.start, reference.end, f"![{alt}]({uri})"))
    normalized = plan.markdown
    for start, end, replacement in reversed(replacements):
        normalized = normalized[:start] + replacement + normalized[end:]
    generated: list[Path] = []
    try:
        fd, name = tempfile.mkstemp(prefix="normalized-", suffix=".md", dir=directory)
        os.close(fd)
        normalized_path = Path(name)
        generated.append(normalized_path)
        normalized_path.write_text(normalized, encoding="utf-8")
        manifest = {
            "version": 1,
            "userId": user_id,
            "datasetId": dataset_id,
            "fileId": file_id,
            "documentPath": plan.document_path,
            "matchMode": plan.match_mode,
            "source": {
                "originalObjectKey": original_key,
                "normalizedObjectKey": normalized_key,
                "originalSha256": hashlib.sha256(original_path.read_bytes()).hexdigest(),
                "normalizedSha256": hashlib.sha256(normalized.encode()).hexdigest(),
            },
            "images": list(image_entries.values()),
            "references": plan.summary["issues"],
            "summary": plan.summary,
            "generatedAt": datetime.now().isoformat(),
        }
        fd, name = tempfile.mkstemp(prefix="manifest-", suffix=".json", dir=directory)
        os.close(fd)
        manifest_path = Path(name)
        generated.append(manifest_path)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        uploads = (
            BundleUpload(original_path, original_key, "text/markdown"),
            *image_uploads.values(),
            BundleUpload(normalized_path, normalized_key, "text/markdown"),
            BundleUpload(manifest_path, prefix + "manifest.json", "application/json"),
        )
        return normalized_key, tuple(uploads), (normalized_path, manifest_path)
    except Exception:
        for path in generated:
            path.unlink(missing_ok=True)
        raise
