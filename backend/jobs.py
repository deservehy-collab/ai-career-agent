"""后台任务管理器：把长耗时的模型调用移出 HTTP 请求线程。

为什么默认必须是单工作线程
--------------------------
``runs/growth.json`` 与 ``runs/loop.json`` 的读-改-写只在**进程内**串行安全
（tests/test_readonly_boundary.py 明确写着"不承诺跨进程"）。而「下一轮规划」
会经由 ``growth_node`` 正式写入成长历史，两个此类任务并发就会互相覆盖；
分析链路还会临时改写 ``agents.growth_agent`` 的**进程级全局 store**。
因此 ``max_workers=1``，把所有重活串成一条队列 —— 队列是特性，不是缺陷。

两条上限（都默认关闭，由 backend.config 在生产入口注入）
--------------------------------------------------------
- ``max_records``：记录只存在内存里，一次分析产出的完整 state 不小。超上限时
  从最旧的开始丢，**只丢已终态**的记录；``queued`` / ``running`` 永不丢，
  否则 ``_execute`` 查不到自己的记录、前端也会拿着一个永远查不到的 run_id。
- ``max_pending``：同时在跑或排队的任务数上限。单 worker + 一次几分钟的推理，
  没有上限时双击"开始分析"会排出一串重复任务。满了就抛 ``QueueFull``，
  由 ``backend.app`` 的异常处理器翻成 HTTP 503。
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
    "TERMINAL_STATUSES", "TaskRecord", "TaskManager", "QueueFull",
]

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

#: 终态集合：查询接口据此判断"跑完了没有"。
TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED)


class QueueFull(RuntimeError):
    """在跑/排队的任务数已达上限，本次提交被拒绝（HTTP 层翻成 503）。"""


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

    def __init__(
        self,
        max_workers: int = 1,
        max_records: int | None = None,
        max_pending: int | None = None,
    ) -> None:
        """``max_records`` / ``max_pending`` 传 ``None`` 表示不限（单测与 CLI 用），
        生产入口由 ``backend.config`` 注入具体数值。"""
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="career-job"
        )
        self._lock = threading.Lock()
        self._records: dict[str, TaskRecord] = {}
        self._max_records = max_records
        self._max_pending = max_pending

    # ── 提交 ────────────────────────────────────────────────────────────
    def submit(self, fn: Callable[..., Any], *args: Any, kind: str = "job", **kwargs: Any) -> str:
        """把 ``fn(*args, **kwargs)`` 排进队列，立刻返回 ``run_id``。

        队列已满时抛 :class:`QueueFull`，**不会**创建记录、也不会占用线程池。
        """
        run_id = uuid.uuid4().hex
        with self._lock:
            self._reject_when_queue_full_locked()
            self._drop_oldest_finished_locked()
            self._records[run_id] = TaskRecord(run_id=run_id, kind=kind)
        self._executor.submit(self._execute, run_id, fn, args, kwargs)
        return run_id

    def _pending_count_locked(self) -> int:
        return sum(1 for record in self._records.values() if not record.done)

    def _reject_when_queue_full_locked(self) -> None:
        if self._max_pending is None:
            return
        pending = self._pending_count_locked()
        if pending >= self._max_pending:
            raise QueueFull(f"后台队列已满（{pending} 个任务在跑或排队），请稍后再试")

    def _drop_oldest_finished_locked(self) -> None:
        """超过记录上限时，按创建顺序从最旧开始丢**已终态**的记录。

        ``dict`` 保持插入顺序，所以"最旧"就是迭代顺序的前端。
        """
        if self._max_records is None:
            return
        for run_id, record in list(self._records.items()):
            if len(self._records) < self._max_records:
                break
            if record.done:
                self._records.pop(run_id)

    def _execute(self, run_id: str, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:  # 已被清理，不再执行
                return
            record.status = STATUS_RUNNING
            record.started_at = _now()

        try:
            result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 业务失败不抛给调用方，写进 record 由查询接口回报
            with self._lock:
                record.status = STATUS_FAILED
                record.error = f"{type(exc).__name__}: {exc}"
                record.finished_at = _now()
            return
        except BaseException as exc:
            # SystemExit / KeyboardInterrupt / MemoryError 一类进程级信号：
            # 先如实落账（否则记录会永远停在 running），再原样抛出，不在这里吞掉。
            with self._lock:
                record.status = STATUS_FAILED
                record.error = f"进程级异常 {type(exc).__name__}: {exc}"
                record.finished_at = _now()
            raise

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

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """关闭线程池。

        ``cancel_futures=True`` 时排队中的任务不再执行。先关线程池、后落账：
        正在跑的任务只可能变成终态，标 ``STATUS_FAILED`` 只命中仍停在
        ``queued`` 的那些，不会覆盖真实结果。
        """
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
        if cancel_futures:
            with self._lock:
                for record in self._records.values():
                    if record.status == STATUS_QUEUED:
                        record.status = STATUS_FAILED
                        record.error = "服务已停止，任务未开始执行"
                        record.finished_at = _now()
