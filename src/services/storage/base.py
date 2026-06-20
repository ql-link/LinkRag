from abc import ABC, abstractmethod
from pathlib import Path


class BaseObjectStorage(ABC):
    """对象存储抽象接口。

    下载侧仅暴露 ``download_to_path``：实现必须保证整个调用栈内不出现"完整对象 bytes"的
    内存对象，以避免 worker 在大文件 / 高并发场景下 OOM。原 ``download_bytes`` 已下线。
    """

    @abstractmethod
    def download_to_path(self, bucket: str, object_key: str, dst: Path) -> None:
        """流式下载对象到本地路径。

        实现需保证整个调用栈内不在内存中拼接完整对象 bytes；磁盘满（``OSError`` errno=ENOSPC）
        允许向上抛，由调用方分类为 ``TEMP_DISK_FULL``。其他对象存储侧异常向上抛由调用方
        归类为 ``SOURCE_FILE_NOT_FOUND``。
        """

    @abstractmethod
    def upload_bytes(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        """上传对象内容。"""

    @abstractmethod
    def build_object_url(self, bucket: str, object_key: str) -> str:
        """构造对象访问 URL。"""

    @abstractmethod
    def remove_prefix(self, bucket: str, prefix: str) -> int:
        """删除某前缀下的全部对象，返回删除的对象数。

        用于删除链路按解析任务目录前缀清理 OSS 产物（Markdown + 图片同在
        ``parsed/.../{taskId}/`` 下）。约定：

        - 前缀下无对象时为 no-op（返回 0），不报错——支撑删除幂等与"删不存在产物"安全。
        - 空前缀必须拒绝（返回 0 或抛错），避免误删整桶；调用方只应传具体 taskId 目录前缀。
        - 对象存储侧的网络 / 超时异常向上抛，由删除编排归类为暂时性失败重试。
        """
