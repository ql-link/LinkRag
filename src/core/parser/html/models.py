from dataclasses import dataclass, field


@dataclass(slots=True)
class HtmlParseOptions:
    """HTML parser runtime options."""

    source_file_url: str | None = None
    image_prefix: str = "html-images"
    mock_minio_base_url: str = "mock-minio://tolink-rag"


@dataclass(slots=True)
class ImageRewriteResult:
    """Result of normalizing an HTML image reference."""

    markdown: str
    original_url: str
    absolute_url: str
    object_url: str | None
    warning: str | None = None


@dataclass(slots=True)
class TableRenderResult:
    """Rendered Markdown for a single HTML table."""

    markdown: str
    strategy: str
    warning: str | None = None
    image_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HtmlParseResult:
    """Structured output before adapting to BaseParser."""

    markdown: str
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
