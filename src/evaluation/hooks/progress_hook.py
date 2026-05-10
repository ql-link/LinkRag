# -*- coding: utf-8 -*-
"""ProgressHook — 基于 tqdm 或 rich 的进度条 Hook（优先 rich，降级 tqdm，再降级打印）。"""
from __future__ import annotations

import sys

from src.evaluation.contracts.hook import (
    EvalEvent, EVENT_RUN_START, EVENT_SAMPLE_DONE, EVENT_RUN_COMPLETE,
)


class ProgressHook:
    """评估进度条 Hook。

    自动检测可用库：rich → tqdm → 简单 print。
    进度条追踪 SAMPLE_DONE 事件，在 RUN_COMPLETE 时关闭。
    """

    def __init__(self) -> None:
        self._pbar = None
        self._total = 0
        self._done = 0

    async def on_event(self, event: EvalEvent) -> None:
        """处理评估事件，更新进度条。

        Args:
            event: 评估事件对象。
        """
        et = event.event_type
        p = event.payload

        if et == EVENT_RUN_START:
            self._total = p.get("sample_count", 0)
            self._done = 0
            self._pbar = self._create_pbar(self._total, p.get("dataset_name", ""))

        elif et == EVENT_SAMPLE_DONE:
            self._done += 1
            if self._pbar is not None:
                self._advance_pbar(self._pbar)
            else:
                print(
                    f"\r进度: {self._done}/{self._total}",
                    end="", flush=True,
                )

        elif et == EVENT_RUN_COMPLETE:
            if self._pbar is not None:
                self._close_pbar(self._pbar)
                self._pbar = None
            else:
                print()  # 换行

    @staticmethod
    def _create_pbar(total: int, desc: str):
        """尝试创建进度条，失败时返回 None。"""
        try:
            from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
            pbar = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
            )
            pbar.__enter__()
            pbar._task_id = pbar.add_task(desc or "evaluating", total=total)
            return pbar
        except ImportError:
            pass

        try:
            import tqdm
            return tqdm.tqdm(total=total, desc=desc or "evaluating", file=sys.stderr)
        except ImportError:
            return None

    @staticmethod
    def _advance_pbar(pbar) -> None:
        """推进进度条。"""
        try:
            # rich.Progress
            if hasattr(pbar, "_task_id"):
                pbar.advance(pbar._task_id)
            else:
                pbar.update(1)
        except Exception:
            pass

    @staticmethod
    def _close_pbar(pbar) -> None:
        """关闭进度条。"""
        try:
            if hasattr(pbar, "__exit__"):
                pbar.__exit__(None, None, None)
            elif hasattr(pbar, "close"):
                pbar.close()
        except Exception:
            pass
