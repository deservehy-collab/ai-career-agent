"""``GET /api/tasks`` 的分页参数。

约束：``limit`` / ``offset`` 只对返回的 ``tasks`` 数组开窗；
``rounds`` 与 ``summary`` 永远是**全量口径**，另附 ``pagination`` 块说明窗口。
不传参数时默认 ``limit=500`` —— 不带分页参数的老前端行为不变。

隔离：store 全部在临时目录 + ``dependency_overrides`` 注入，不碰项目 runs/。
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from agents.growth_store import GrowthStore  # noqa: E402
from agents.loop_store import LoopStore  # noqa: E402
from backend.app import app  # noqa: E402
from backend.deps import create_stores  # noqa: E402
from backend.services import Stores  # noqa: E402

LEARNING_COUNT = 3
PROJECT_COUNT = 2
TOTAL = LEARNING_COUNT + PROJECT_COUNT


class TasksPaginationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        loop = LoopStore(directory=self._tmp.name)
        learning = [{"topic": f"知识点{i}", "covers": []} for i in range(1, LEARNING_COUNT + 1)]
        projects = [{"name": f"项目{i}", "covers_gaps": []} for i in range(1, PROJECT_COUNT + 1)]
        written = loop.append_round("软件工程师", learning, projects, round_no=1)
        assert written["status"] == "written", written

        self._stores = Stores(growth=GrowthStore(directory=self._tmp.name), loop=loop)
        app.dependency_overrides[create_stores] = lambda: self._stores
        self.client = TestClient(app)
        self.addCleanup(app.dependency_overrides.pop, create_stores, None)
        self.addCleanup(self._tmp.cleanup)

    def test_default_returns_all_tasks(self):
        body = self.client.get("/api/tasks").json()
        self.assertEqual(body["summary"]["total"], TOTAL)
        self.assertEqual(len(body["tasks"]), TOTAL)
        self.assertEqual(body["pagination"]["returned"], TOTAL)
        self.assertEqual(body["pagination"]["total"], TOTAL)

    def test_limit_and_offset_window_the_task_array(self):
        body = self.client.get("/api/tasks", params={"limit": 2, "offset": 1}).json()
        self.assertEqual(len(body["tasks"]), 2)
        self.assertEqual(body["pagination"],
                         {"limit": 2, "offset": 1, "returned": 2, "total": TOTAL})
        # summary 是全量口径，不随窗口缩水
        self.assertEqual(body["summary"]["total"], TOTAL)
        # 窗口内容正确：第 2、3 个任务（task_id 有序）
        self.assertEqual([t["index"] for t in body["tasks"]], [2, 3])

    def test_offset_beyond_total_returns_empty_window(self):
        body = self.client.get("/api/tasks", params={"offset": 99}).json()
        self.assertEqual(body["tasks"], [])
        self.assertEqual(body["pagination"]["returned"], 0)
        self.assertEqual(body["summary"]["total"], TOTAL)

    def test_invalid_limit_is_422(self):
        self.assertEqual(
            self.client.get("/api/tasks", params={"limit": 0}).status_code, 422)
        self.assertEqual(
            self.client.get("/api/tasks", params={"limit": -1}).status_code, 422)
        self.assertEqual(
            self.client.get("/api/tasks", params={"limit": 99999}).status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
