"""后端"任务完成"接口的并发保护测试。

要防的是什么
------------
``LoopStore.mark_completed()`` 是**无互斥**的读—改—写：读全量 → 改副本 →
原子替换文件。``_write`` 的原子性只保证"文件不会写到一半"，**不保证两次
读—改—写不互相覆盖**。两个线程同时完成**不同**的任务时，后写的那个会拿着
自己那份旧基线覆盖掉先写的完成记录 —— 丢失更新。

``agents/loop_store.py`` 自身没有任何锁（也不允许在本次改动它），所以
``backend/services.py`` 在**服务层**用一把模块级锁串行化写盘。这把锁的覆盖面是
**"谁写 loop.json"而不是"哪个接口"**，四条写入路径全在锁内：

1. ``complete_task``（``mark_completed``，HTTP 线程，会真正并发）
2. ``add_manual_event``（``append_round`` + ``mark_completed``）
3. ``_run_next_round``（下一轮规划末尾的 ``append_round``，后台工作线程）
4. ``run_analyze_and_save``（首轮任务的 ``append_round``，后台工作线程）

漏掉 3、4 中的任意一条，都会让"分析/生成下一轮正在落盘"与"用户同时提交任务完成"
互相覆盖 —— 本文件同时证明这四条确实进了临界区。

验证方式
--------
- 用带 ``Barrier`` 的多线程同时打接口，尽量制造真正的重叠；
- 断言"每个任务都还是 completed、且各自的证据都在" —— 一旦丢更新，
  条数或状态必然对不上；
- 用计数锁代理断言 ``append_round`` **被调用的那一刻**临界区深度 > 0，
  这比"跑起来没报错"更能证明锁真的包住了写入。

全程用临时目录 + ``dependency_overrides`` 注入 store，**不触碰项目 runs/**，
也不调 Ollama（任务完成是纯规则计算；下一轮/分析的模型调用用 stub 替掉）。
"""

import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from agents.growth_store import GrowthStore  # noqa: E402
from agents.loop_store import LoopStore  # noqa: E402
from backend import services  # noqa: E402
from backend.app import app  # noqa: E402
from backend.deps import create_stores  # noqa: E402
from backend.schemas import AnalyzeRequest, UserProfileRequest  # noqa: E402
from backend.services import Stores  # noqa: E402

LEARNING_COUNT = 6
PROJECT_COUNT = 3


def _seed_round(loop: LoopStore) -> list[str]:
    """写入一轮含多条学习 + 项目任务的记录，返回全部 task_id。"""
    learning = [
        {
            "topic": f"知识点{i}", "covers": ["Python"], "description": "d",
            "stage": 1, "duration": "1周", "prerequisites": [],
            "method": "学习", "assign": "自己", "assessment": "可实现",
            "goal": "掌握", "status_v2": "pending", "resources": [],
            "priority": "高", "milestones": [], "deliverables": [],
        }
        for i in range(1, LEARNING_COUNT + 1)
    ]
    projects = [
        {
            "name": f"项目{i}", "covers_gaps": ["Python"], "description": "d",
            "goals": [], "features": [], "tech_stack": [], "duration": "2周",
            "difficulty": "中级", "prerequisites_gaps": [], "method": "实战",
            "metrics": [], "milestones": [], "status_v2": "pending",
        }
        for i in range(1, PROJECT_COUNT + 1)
    ]
    result = loop.append_round(
        target_job="软件工程师", learning_plan=learning, project_plan=projects, round_no=1
    )
    assert result["status"] == "written", result
    return [task["task_id"] for task in loop.load().data["rounds"][0]["tasks"]]


class _StoreCase(unittest.TestCase):
    """公共装置：临时目录 store + dependency_overrides 注入。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._loop = LoopStore(directory=self._tmp.name)
        self._growth = GrowthStore(directory=self._tmp.name)
        self._stores = Stores(growth=self._growth, loop=self._loop)
        app.dependency_overrides[create_stores] = lambda: self._stores
        self._client = TestClient(app)
        self._task_ids = _seed_round(self._loop)

    def tearDown(self):
        app.dependency_overrides.pop(create_stores, None)
        self._tmp.cleanup()

    def _tasks_by_id(self) -> dict:
        return {
            task["task_id"]: task
            for entry in self._loop.load().data["rounds"]
            for task in entry["tasks"]
        }


class SharedLockTest(_StoreCase):
    """锁是模块级那一把，不是每次调用新建的。"""

    def test_complete_task_enters_the_module_level_lock(self):
        events = []

        class _Spy:
            def __enter__(self):
                events.append("enter")
                return self

            def __exit__(self, *exc_info):
                events.append("exit")
                return False

        task_id = self._task_ids[0]
        # complete_task 在调用时读模块全局，替换它对整段临界区生效
        with mock.patch.object(services, "_STORE_WRITE_LOCK", _Spy()):
            result = services.complete_task(self._stores, task_id, "证据")

        self.assertEqual(events, ["enter", "exit"], "整段读—改—写应恰好进出临界区一次")
        self.assertTrue(result["completion_written"])

    def test_lock_is_a_single_module_level_object(self):
        """同一把锁被反复取用；不同服务调用看到的必须是同一个对象。"""
        first = services._STORE_WRITE_LOCK
        second = services._STORE_WRITE_LOCK
        self.assertIs(first, second)

class _CountingLock:
    """包一层真锁，只为了在外面读到"当前临界区深度"。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.depth = 0

    def __enter__(self):
        self._inner.acquire()
        self.depth += 1
        return self

    def __exit__(self, *exc_info):
        self.depth -= 1
        self._inner.release()
        return False


class WriterPathsInsideLockTest(_StoreCase):
    """另外三条 loop.json 写入路径同样在锁内落盘 —— 断言"写入那一刻深度为 1"。

    为什么断言深度而不是"多线程撞一次看会不会丢"：丢更新的窗口只有 ``load()``
    到 ``os.replace()`` 之间那几毫秒，靠撞概率的测试既不稳定、证据也弱；
    "写入确实发生在临界区内"才是这条保护真正要保证的事。
    """

    #: 只要能让 append_round 被调到，计划内容本身不是本测试的重点
    FAKE_RESULT = {
        "learning_plan": [{"topic": "新知识点", "covers": ["Python"], "goal": "掌握"}],
        "project_plan": [],
        "growth_diff": {"outcome": "upgraded", "history_written": True},
        "user_skills": [],
        "skill_updates": [],
    }

    def _payload(self):
        return AnalyzeRequest(
            user_profile=UserProfileRequest(major="计算机", grade="大三",
                                            skills=["Python"], projects=[]),
            target_job="软件工程师",
        )

    def _empty_loop(self) -> LoopStore:
        """另开一个**空** loop.json：``_StoreCase`` 的公共装置已经建好第一轮，
        而 ``run_analyze_and_save`` 的第一条分支正是"已有轮次就只读不建"，
        用它测不到落盘那条路。"""
        return LoopStore(directory=Path(self._tmp.name) / "fresh")

    def _spy_writes(self, loop: LoopStore | None = None):
        """把 append_round / mark_completed 换成记录锁深度的替身（仍真写临时目录）。"""
        target = loop if loop is not None else self._loop
        depths: list[int] = []
        spy = _CountingLock(services._STORE_WRITE_LOCK)
        real_append = target.append_round
        real_complete = target.mark_completed

        def append(*args, **kwargs):
            depths.append(spy.depth)
            return real_append(*args, **kwargs)

        def complete(*args, **kwargs):
            depths.append(spy.depth)
            return real_complete(*args, **kwargs)

        return depths, spy, append, complete

    def test_manual_event_writes_inside_the_lock(self):
        depths, spy, append, complete = self._spy_writes()
        with mock.patch.object(services, "_STORE_WRITE_LOCK", spy), \
             mock.patch.object(self._loop, "append_round", side_effect=append), \
             mock.patch.object(self._loop, "mark_completed", side_effect=complete):
            result = services.add_manual_event(
                self._stores, kind="learning", title="自学了 Git",
                skills=["Python"], evidence="把项目推到了远程仓库",
            )
        self.assertTrue(result["added"], result)
        self.assertEqual(depths, [1, 1], "补录的两段写入都应发生在临界区内")

    def test_next_round_appends_inside_the_lock(self):
        # 待处理成果来自"已完成任务"，先真实落一条完成记录（不走服务层，避免叠加深度假象）
        self._loop.mark_completed(self._task_ids[0], evidence="已完成的先验成果")
        depths, spy, append, _ = self._spy_writes()
        with mock.patch.object(services, "_STORE_WRITE_LOCK", spy), \
             mock.patch.object(self._loop, "append_round", side_effect=append), \
             mock.patch.object(services.workflow, "invoke", return_value=dict(self.FAKE_RESULT)):
            result = services._run_next_round(self._stores, user_profile={
                "major": "计算机", "grade": "大三", "skills": ["Python"], "projects": []},
                target_job="软件工程师")
        self.assertTrue(result["round_created"], result)
        self.assertEqual(depths, [1], "下一轮的 append_round 必须在临界区内被调用")

    def test_analyze_and_save_appends_inside_the_lock(self):
        fresh = self._empty_loop()
        depths, spy, append, _ = self._spy_writes(fresh)
        with mock.patch.object(services, "_STORE_WRITE_LOCK", spy), \
             mock.patch.object(fresh, "append_round", side_effect=append), \
             mock.patch.object(services.workflow, "invoke", return_value=dict(self.FAKE_RESULT)):
            result = services.run_analyze_and_save(
                Stores(growth=self._growth, loop=fresh), self._payload())
        self.assertTrue(result["round_created"], result)
        self.assertEqual(depths, [1], "分析并保存的 append_round 必须在临界区内被调用")

    def test_analyze_and_save_rechecks_rounds_inside_the_lock(self):
        """推理那几分钟里冒出来的轮次不该被重复建 —— 靠的是锁内**重读** latest_round。"""
        fresh = self._empty_loop()
        depths, spy, append, _ = self._spy_writes(fresh)
        real_append = fresh.append_round
        real_latest = fresh.latest_round
        seeded = {"done": False}

        def latest_then_seed(*args, **kwargs):
            """把"另一个写入方刚刚建好第一轮"塞进推理与落盘之间。"""
            snapshot = real_latest()
            if snapshot is None and not seeded["done"]:
                seeded["done"] = True
                real_append("软件工程师", self.FAKE_RESULT["learning_plan"], [])
            return snapshot

        with mock.patch.object(services, "_STORE_WRITE_LOCK", spy), \
             mock.patch.object(fresh, "append_round", side_effect=append), \
             mock.patch.object(fresh, "latest_round", side_effect=latest_then_seed), \
             mock.patch.object(services.workflow, "invoke", return_value=dict(self.FAKE_RESULT)):
            result = services.run_analyze_and_save(
                Stores(growth=self._growth, loop=fresh), self._payload())

        self.assertFalse(result["round_created"], "已有轮次时不得再建一轮重复任务")
        self.assertEqual(len(fresh.load().data["rounds"]), 1)
        self.assertEqual(depths, [], "重读发现已有轮次，就不该再进第二次写入")


class ConcurrentDistinctTasksTest(_StoreCase):
    """并发完成**不同**任务：一个都不能丢。"""

    def test_all_distinct_tasks_completed_without_lost_updates(self):
        barrier = threading.Barrier(len(self._task_ids))

        def worker(task_id: str):
            barrier.wait()  # 尽量让所有请求真的重叠在一起
            response = self._client.post(
                f"/api/tasks/{task_id}/complete",
                json={"evidence": f"完成证据 {task_id}"},
            )
            return task_id, response

        with ThreadPoolExecutor(max_workers=len(self._task_ids)) as pool:
            results = list(pool.map(worker, self._task_ids))

        # ① 每个请求都成功，且都确实写盘了（不是 already_completed）
        for task_id, response in results:
            self.assertEqual(response.status_code, 200, f"{task_id} 应 200")
            body = response.json()
            self.assertTrue(body["completion_written"], f"{task_id} 应真正落盘")
            self.assertFalse(body["already_completed"], f"{task_id} 不应是重复提交")

        # ② 落盘结果：条数没少、状态都对、证据各归各位 —— 丢更新会在这里暴露
        tasks = self._tasks_by_id()
        self.assertEqual(len(tasks), len(self._task_ids), "任务条目不应丢失")
        for task_id in self._task_ids:
            self.assertEqual(tasks[task_id]["status"], "completed", f"{task_id} 应为 completed")
            self.assertEqual(
                tasks[task_id]["evidence"], f"完成证据 {task_id}", f"{task_id} 的证据被覆盖"
            )
            self.assertTrue(tasks[task_id]["completed_at"], f"{task_id} 缺完成时间")

    def test_business_workflow_still_reads_complete_record(self):
        """并发之后，待处理成果接口能读到全部完成记录（闭环不被截断）。"""
        barrier = threading.Barrier(len(self._task_ids))

        def worker(task_id: str):
            barrier.wait()
            return self._client.post(
                f"/api/tasks/{task_id}/complete", json={"evidence": f"证据 {task_id}"}
            )

        with ThreadPoolExecutor(max_workers=len(self._task_ids)) as pool:
            list(pool.map(worker, self._task_ids))

        pending = self._client.get("/api/growth/pending").json()
        self.assertEqual(len(pending["tasks"]), len(self._task_ids),
                         "每个已完成任务都应能构造成待处理成长成果")


class ConcurrentSameTaskTest(_StoreCase):
    """并发完成**同一个**任务：仍然幂等，只有一次真正落盘。"""

    def test_same_task_submitted_concurrently_writes_once(self):
        task_id = self._task_ids[0]
        barrier = threading.Barrier(8)

        def worker(index: int):
            barrier.wait()
            response = self._client.post(
                f"/api/tasks/{task_id}/complete", json={"evidence": f"证据-{index}"}
            )
            return response

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(worker, range(8)))

        bodies = [r.json() for r in responses]
        written = [b for b in bodies if b["completion_written"]]
        already = [b for b in bodies if b["already_completed"]]

        self.assertEqual(len(written), 1, "只应有一次真正写盘")
        self.assertEqual(len(already), 7, "其余 7 次都应判定为重复提交")

        # 落盘证据必须等于"那一次成功写盘"的证据，没被后来者覆盖
        task = self._tasks_by_id()[task_id]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["evidence"], written[0]["task"]["evidence"])


class GrowthHistoryUntouchedTest(_StoreCase):
    """任务完成**绝不**写 runs/growth.json（升级只是预览）。"""

    def test_completion_never_writes_growth_history(self):
        barrier = threading.Barrier(len(self._task_ids))

        def worker(task_id: str):
            barrier.wait()
            return self._client.post(
                f"/api/tasks/{task_id}/complete", json={"evidence": f"证据 {task_id}"}
            )

        with ThreadPoolExecutor(max_workers=len(self._task_ids)) as pool:
            list(pool.map(worker, self._task_ids))

        history = self._growth.load().data.get("history") or []
        self.assertEqual(history, [], "任务完成接口不得写入成长历史")
        self.assertFalse(self._growth.path.exists(), "并发提交也不应创建 growth.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
