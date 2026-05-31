from __future__ import annotations

from collections.abc import Callable

from src.config import settings
from src.core.parser.pdf.backends.mineru_backend import MinerUBackend
from src.core.parser.pdf.backends.naive_backend import NaivePdfBackend
from src.core.parser.pdf.backends.opendataloader_backend import OpenDataLoaderBackend
from src.core.parser.pdf.base import BasePdfBackend
from src.core.parser.pdf.models import PdfParseOptions


PdfBackendFactory = Callable[[PdfParseOptions], BasePdfBackend | None]
_EXTRA_BACKEND_FACTORIES: dict[str, PdfBackendFactory | type[BasePdfBackend]] = {}


class PdfBackendRegistry:
    """PDF 解析后端注册表。

    Service 只依赖注册表按名称创建后端实例，新增解析器时注册新的 factory 即可，
    不需要修改解析编排流程。
    """

    AUTO_BACKEND_ORDER = ("mineru", "opendataloader", "naive")

    def __init__(
        self,
        *,
        default_backend: str | None = None,
        fallbacks: str | None = None,
    ) -> None:
        self.default_backend = (default_backend or settings.PDF_PARSER_BACKEND or "mineru").lower()
        self.fallbacks = settings.PDF_PARSER_FALLBACKS if fallbacks is None else fallbacks
        self._factories: dict[str, PdfBackendFactory] = {}

    def register(
        self,
        name: str,
        factory: PdfBackendFactory | type[BasePdfBackend],
    ) -> None:
        backend_name = name.strip().lower()
        if not backend_name:
            raise ValueError("PDF 解析器名称不可为空")

        if isinstance(factory, type):
            self._factories[backend_name] = lambda _options, cls=factory: cls()
        else:
            self._factories[backend_name] = factory

    def create(self, name: str, options: PdfParseOptions) -> BasePdfBackend | None:
        factory = self._factories.get((name or "").lower())
        if factory is None:
            return None
        return factory(options)

    def resolve_order(self, backend: str | None) -> list[str]:
        requested = (backend or self.default_backend).lower()
        if requested == "auto":
            return [name for name in self.AUTO_BACKEND_ORDER if name in self._factories]

        primary = requested if requested in self._factories else self.default_backend
        if primary == "mineru":
            return [primary]
        order = [primary]
        for item in (self.fallbacks or "").split(","):
            fallback = item.strip().lower()
            if fallback in self._factories and fallback not in order:
                order.append(fallback)
        return order

    def available_backends(self) -> list[str]:
        return sorted(self._factories)


def create_default_pdf_backend_registry() -> PdfBackendRegistry:
    registry = PdfBackendRegistry()
    registry.register(MinerUBackend.name, _create_mineru_backend)
    registry.register(OpenDataLoaderBackend.name, OpenDataLoaderBackend)
    registry.register(NaivePdfBackend.name, NaivePdfBackend)
    for name, factory in _EXTRA_BACKEND_FACTORIES.items():
        registry.register(name, factory)
    return registry


def register_pdf_backend(
    name: str,
    factory: PdfBackendFactory | type[BasePdfBackend],
) -> None:
    """注册全局 PDF 解析后端。

    注册后，之后新建的默认 PdfParserService 会自动带上该后端。
    """
    backend_name = name.strip().lower()
    if not backend_name:
        raise ValueError("PDF 解析器名称不可为空")
    _EXTRA_BACKEND_FACTORIES[backend_name] = factory


def _create_mineru_backend(options: PdfParseOptions) -> MinerUBackend | None:
    api_url = getattr(options, "mineru_api_url", None) or ""
    if not api_url:
        return None
    return MinerUBackend(
        api_url=api_url,
        api_key=getattr(options, "mineru_api_key", None),
        timeout=getattr(options, "mineru_timeout", 300),
    )
