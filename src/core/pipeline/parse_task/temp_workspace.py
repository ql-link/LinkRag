"""解析任务临时落盘目录治理。

集中管理 ``PARSE_TEMP_DIR`` 的：

- 启动清理（``ensure_clean_on_startup``）：worker 启动时确保目录存在且为空，兜底回收
  进程异常退出残留的临时文件。
- 临时文件分配（``create_temp_file``）：按 ``parse-{task_id}-{rand}.tmp`` 命名隔离同
  task_id 重投与并发场景。
- 幂等删除（``safe_unlink``）：早删与 finally 兜底使用同一入口，避免 ``FileNotFoundError``
  污染失败兜底链路。

设计意图：把"谁创建谁清理"的语义封装到本模块，``pipeline._run`` 只需调用这三个函数，
不在主流程里散写文件系统操作。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from loguru import logger


def ensure_clean_on_startup(temp_dir: Path) -> None:
    """worker 启动时确保 ``PARSE_TEMP_DIR`` 存在且不残留旧文件。

    单消费者模型下不存在"启动时还有别的 worker 在写文件"的并发问题，直接清空目录内
    顶层文件。子目录不递归删除——本模块仅产出平铺临时文件，子目录非预期产物，保留
    以便人工排查。

    mkdir / unlink 失败让异常上抛，阻止 worker 启动，避免后续 ``download_to_path``
    永远失败但运维不知。
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in temp_dir.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink(missing_ok=True)
            removed += 1
    logger.info(
        "[temp_workspace] startup clean: dir={} removed={}",
        temp_dir,
        removed,
    )


def create_temp_file(task_id: str, temp_dir: Path) -> Path:
    """生成命名隔离的临时文件路径（不创建实际文件）。

    实际写入由 ``storage.download_to_path`` 完成；本函数只负责生成唯一路径。命名格式
    ``parse-{task_id}-{uuid4 hex[:8]}.tmp``：

    - ``task_id`` 便于异常时人工定位归属
    - 8 位随机 hex 兜底极端 MQ 重投 / 同 task_id 并发场景的命名碰撞
    """
    name = f"parse-{task_id}-{uuid.uuid4().hex[:8]}.tmp"
    return temp_dir / name


def safe_unlink(path: Path | None) -> None:
    """幂等删除临时文件：``None`` 或不存在路径不抛错。

    主路径"早删"与 finally"兜底删"使用同一入口，因此必须幂等——markdown 上传失败
    场景下临时文件已经早删，finally 不能再抛 ``FileNotFoundError``。其他 ``OSError``
    （权限等）仅 warning 不上抛，避免遮蔽业务失败原因。
    """
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "[temp_workspace] unlink failed: path={} error={}",
            path,
            exc,
        )
