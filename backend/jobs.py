"""后台任务管理器：把长耗时的模型调用移出 HTTP 请求线程。

为什么默认必须是单工作线程
--------------------------
``runs/growth.json`` 与 ``runs/loop.json`` 的读-改-写只在**进程内**串行安全
（tests/test_readonly_boundary.py 明确写着"不承诺跨进程"）。而「下一轮规划」
会经由 ``growth_node`` 正式写入成长历史，两个此类任务并发就会互相覆盖；
分析链路还会临时改写 ``agents.growth_agent`` 的**进程级全局 store**。
因此 ``max_workers=1``，把所有重活串成一条队列 —— 队列是特性，不是缺陷。
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

__all__ = [
    "STATUS_QUEUED", "STATUS_RUNNING", "STATUS_SUCCEEDED", "STATUS_FAILED",
    "TaskRecord", "TaskManager",
]

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

#: 终态集合：查询接口据此判断"跑完了没有"。
TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class TaskRecord:
    """一次后台运行的记录（``POST`` 返回 run_id，``GET`` 用它查状态）。"""

    run_id: str
    kind: str
    status: str = STATUS_QUEUED
    result: Any = None
    error: str | None = None
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def done(self) -> bool:
        return self.status in TERMINAL_STATUSES


class TaskManager:
    """极简后台任务表：提交 → 排队 → 串行执行 → 记录结果 / 错误。

    失败**不抛给调用方**（提交是异步的），而是把异常消息写进
    ``record.error``，由 ``GET /api/runs/{run_id}`` 如实回报。
    """

    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="career-job"
        )
        self._lock = threading.Lock()
        self._records: dict[str, TaskRecord] = {}

    # ── 提交 ────────────────────────────────────────────────────────────
    def submit(self, fn: Callable[..., Any], *args: Any, kind: str = "job", **kwargs: Any) -> str:
        """把 ``fn(*args, **kwargs)`` 排进队列，立刻返回 ``run_id``。"""
        run_id = uuid.uuid4().hex
        record = TaskRecord(run_id=run_id, kind=kind)
        with self._lock:
            self._records[run_id] = record
        self._executor.submit(self._execute, run_id, fn, args, kwargs)
        return run_id

    def _execute(self, run_id: str, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:  # 已被清理，不再执行
                return
            record.status = STATUS_RUNNING
            record.started_at = _now()

        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - 后台线程必须吞掉一切并如实记录
            with self._lock:
                record.status = STATUS_FAILED
                record.error = f"{type(exc).__name__}: {exc}"
                record.finished_at = _now()
            return

        with self._lock:
            record.status = STATUS_SUCCEEDED
            record.result = result
            record.error = None
            record.finished_at = _now()

    # ── 查询 ────────────────────────────────────────────────────────────
    def get(self, run_id: str) -> TaskRecord | None:
        """取记录对象本身；不存在返回 ``None``（测试直接读 ``.status``）。"""
        with self._lock:
            return self._records.get(run_id)

    def snapshot(self, run_id: str) -> dict | None:
        """取一份脱离锁的记录快照，供 HTTP 序列化。"""
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return None
            return asdict(record)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
