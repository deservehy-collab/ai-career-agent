"""后台运行记录的两条上限（P0-③）。

防的是什么
----------
``TaskManager._records`` 是一张**只存在内存里的表**，原先没有上限：一次分析会把
完整的七节点 state 挂在 ``record.result`` 上，页面多点几次就一直涨，进程不重启
永不释放。同时 ``max_workers=1`` 意味着一次推理要几分钟，没有排队上限时
"双击开始分析"会排出两三个重复任务，白等也白算。

两条规则
--------
- ``max_records``：超上限从**最旧**的开始丢，只丢 ``succeeded`` / ``failed``；
  ``queued`` / ``running`` 永不丢 —— 丢了 ``_execute`` 就查不到自己的记录，
  前端也会拿着一个永远查不到的 run_id。所以它是"软上限"：队列堵死时允许超出。
- ``max_pending``：同时"在跑或排队"的任务数上限，满了 ``submit`` 抛 ``QueueFull``，
  由 ``backend.app`` 的处理器翻成 HTTP **503**，响应体 ``{"detail": "..."}``。

零副作用：只用内存里的替身函数，不调模型、不碰 ``runs/``。
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from agents.growth_store import GrowthStore  # noqa: E402
from agents.loop_store import LoopStore  # noqa: E402
from backend.app import app  # noqa: E402
from backend.auth import get_current_user  # noqa: E402
from backend.deps import create_stores, create_task_manager  # noqa: E402
from backend.jobs import QueueFull, TaskManager  # noqa: E402
from backend.services import Stores  # noqa: E402

ANALYZE_BODY = {
    "user_profile": {"major": "计算机", "grade": "大三", "skills": ["Python"], "projects": []},
    "target_job": "软件工程师",
}


def _noop():
    return {"ok": True}


def _wait_done(manager: TaskManager, run_id: str, timeout: float = 5.0) -> None:
    """等到这条记录进终态，让"淘汰最旧"这件事变得可预测。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = manager.get(run_id)
        if record is not None and record.done:
            return
        time.sleep(0.01)
    raise AssertionError(f"run_id={run_id} 在 {timeout}s 内没进入终态")


class RecordCapTest(unittest.TestCase):
    def test_pruning_keeps_the_newest_records(self):
        manager = TaskManager(max_workers=1, max_records=3)
        self.addCleanup(manager.shutdown, True)

        run_ids = []
        for _ in range(5):
            run_id = manager.submit(_noop, kind="analyze")
            _wait_done(manager, run_id)  # 全部落到终态后再提交下一条
            run_ids.append(run_id)

        kept = set(manager._records)
        self.assertEqual(kept, set(run_ids[-3:]), "只应留下最新的 3 条")
        for dropped in run_ids[:2]:
            self.assertIsNone(manager.snapshot(dropped), "被淘汰的 run_id 查询应返回 None")

    def test_in_flight_records_are_never_pruned(self):
        release = threading.Event()
        manager = TaskManager(max_workers=1, max_records=2)
        # addCleanup 是 LIFO：先注册 shutdown、后注册 set，收尾时才会先放行再收线程。
        self.addCleanup(manager.shutdown, True)
        self.addCleanup(release.set)

        blocker = manager.submit(release.wait, 5, kind="blocking")
        tail = [manager.submit(_noop, kind="analyze") for _ in range(4)]

        kept = set(manager._records)
        self.assertIn(blocker, kept, "正在跑的记录不得被淘汰")
        self.assertTrue(set(tail) <= kept, "还没轮到执行（queued）的记录不得被淘汰")


class QueueCapTest(unittest.TestCase):
    def test_submit_raises_once_the_queue_is_full(self):
        release = threading.Event()
        manager = TaskManager(max_workers=1, max_pending=2)
        self.addCleanup(manager.shutdown, True)
        self.addCleanup(release.set)

        first = manager.submit(release.wait, 5, kind="analyze")
        second = manager.submit(_noop, kind="analyze")

        with self.assertRaises(QueueFull) as caught:
            manager.submit(_noop, kind="analyze")

        self.assertIn("队列已满", str(caught.exception))
        self.assertEqual(set(manager._records), {first, second}, "被拒绝的提交不应留下记录")


class QueueFullHttpTest(unittest.TestCase):
    """503 是**响应体形状**的一部分：与 HTTPException 同构，前端按 detail 读文案。"""

    def setUp(self):
        self.release = threading.Event()
        self.manager = TaskManager(max_workers=1, max_pending=1)
        self.addCleanup(self.manager.shutdown, True)
        self.addCleanup(self.release.set)
        # 先把唯一的槽位占住，之后的任何提交都应被拒
        self.manager.submit(self.release.wait, 5, kind="blocking")

        self.client = TestClient(app)
        directory = Path(tempfile.mkdtemp())
        stores = Stores(growth=GrowthStore(directory=directory),
                        loop=LoopStore(directory=directory))
        saved_auth = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "u"}
        app.dependency_overrides[create_stores] = lambda: stores
        app.dependency_overrides[create_task_manager] = lambda: self.manager

        def restore():
            for dependency in (get_current_user, create_stores, create_task_manager):
                app.dependency_overrides.pop(dependency, None)
            if saved_auth is not None:
                app.dependency_overrides[get_current_user] = saved_auth

        self.addCleanup(restore)

    def test_analyze_endpoints_return_503_when_queue_is_full(self):
        for path, body in (
            ("/api/analyze", ANALYZE_BODY),
            ("/api/analyze-and-save", ANALYZE_BODY),
            ("/api/growth/next-round", None),
        ):
            with self.subTest(path=path):
                response = self.client.post(path, json=body) if body is not None \
                    else self.client.post(path)

                self.assertEqual(response.status_code, 503)
                self.assertEqual(set(response.json()), {"detail"}, "响应体只能有 detail 一个键")
                self.assertIn("队列已满", response.json()["detail"])

    def test_rejected_submit_creates_no_run_id(self):
        before = set(self.manager._records)
        self.client.post("/api/analyze", json=ANALYZE_BODY)
        self.assertEqual(set(self.manager._records), before, "503 时不得新建运行记录")


class ProductionCapsTest(unittest.TestCase):
    """生产入口必须真的带上这两条上限（默认 None 是给单测与 CLI 的）。"""

    def test_task_manager_is_built_with_the_configured_caps(self):
        from unittest import mock

        from backend import config, deps

        deps._default_task_manager.cache_clear()
        self.addCleanup(deps._default_task_manager.cache_clear)

        # 打桩 deps 命名空间里的 TaskManager：只验证"用什么参数构造"，
        # 不真的建线程池 —— 否则关掉单例会拖累同一进程里后面的用例。
        with mock.patch.object(deps, "TaskManager") as built:
            deps.create_task_manager()

        self.assertEqual(built.call_args.kwargs["max_records"], config.TASK_RECORD_CAP)
        self.assertEqual(built.call_args.kwargs["max_pending"], config.TASK_QUEUE_CAP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
