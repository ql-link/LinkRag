class FileDownloader:
    """OSS 流式下载工具类"""
    @staticmethod
    def download(url: str) -> bytes:
        # 这里替换为真实的 requests.get 或 OSS SDK 调用
        print(f"正在从 {url} 下载文件...")
        return b"mock file content"