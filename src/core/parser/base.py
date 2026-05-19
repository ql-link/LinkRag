from abc import ABC, abstractmethod
from pathlib import Path


class IFileParser(ABC):
    """文件解析器协议。

    协议入参为 ``Path | None`` 而非 ``bytes`` —— 配合 ``ParseSourceIO.download_to_path``
    的流式下载，避免源文件以 bytes 形态全量驻留内存。``None`` 仅用于"PDF + MinerU 后端 +
    远端 URL 旁路"场景：该路径下源文件不落本地，parser 直接走 URL 调用云端 API。
    """

    @abstractmethod
    def parse(self, source: Path | None) -> str:
        """读取本地文件路径并返回 Markdown 字符串。

        ``source`` 为 ``None`` 时仅在 MinerU URL 旁路下合法，由具体实现自行决定是否拒绝。
        """


class BaseParser(IFileParser):
    """解析器基类，集中存放跨 provider 复用的校验与元数据逻辑。"""

    metadata: dict

    def __init__(self):
        self.metadata = {}

    def validate_source(self, source: Path | None) -> bool:
        """校验本地源文件存在且非空。

        ``source is None`` 在协议层面合法（仅 MinerU 旁路使用），本基类不在此处抛错；
        是否允许 ``None`` 由具体 parser 在自己的 ``parse`` 入口里判定。其他场景下要求
        路径真实存在且文件非空，保留原 ``validate_stream`` 的"非空"业务语义。
        """
        if source is None:
            return True
        path = Path(source)
        if not path.exists() or not path.is_file():
            raise ValueError("源文件不存在")
        if path.stat().st_size == 0:
            raise ValueError("文件流不可为空")
        return True

    def extract_metadata(self) -> dict:
        return self.metadata
