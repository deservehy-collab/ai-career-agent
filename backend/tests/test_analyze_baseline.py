"""只读分析的基线跟随当前用户（多租户回归）。

旧行为的坑：``run_workflow`` 的只读隔离从 ``growth_agent`` 的**全局默认
store**（数据根目录的 growth.json）复制基线 —— 按用户隔离数据后，那是
错误的文件：分析会看到别人的（或过时的）历史。

新行为：HTTP 层把**当前用户**的 growth store 作为 ``baseline_store`` 传入；
不传时退回全局默认 store（CLI 与既有测试的口径，行为不变）。

全程 mock 掉 ``workflow.invoke``，不调 Ollama、不碰项目 runs/。
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents import growth_agent  # noqa: E402
from agents.growth_store import GrowthStore  # noqa: E402
from agents.loop_store import LoopStore  # noqa: E402
from backend import schemas  # noqa: E402
from backend import services  # noqa: E402


def _payload() -> schemas.AnalyzeRequest:
    return schemas.AnalyzeRequest(
        user_profile=schemas.UserProfileRequest(
            major="软件工程", grade="大三", skills=["Python"], projects=[],
        ),
        target_job="AI 应用工程师",
    )


def _fingerprints(data: dict) -> set[str]:
    return {
        str(event.get("fingerprint"))
        for entry in (data.get("history") or [])
        for event in (entry.get("events") or [])
    }


class BaselineFollowsUserTest(unittest.TestCase):
    def test_isolated_store_copies_the_given_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_store = GrowthStore(directory=root / "user_1")
            user_store.append({
                "events": [{"fingerprint": "user1\t技能\t证据"}],
                "user_skills_after": [],
            })
            decoy_store = GrowthStore(directory=root / "legacy_root")
            decoy_store.append({
                "events": [{"fingerprint": "decoy\t旧全局\t数据"}],
                "user_skills_after": [],
            })

            import backend.analyze as analyze_mod

            previous = growth_agent._store
            growth_agent.set_store(decoy_store)  # 全局默认里放"诱饵"：绝不能再用它当基线
            try:
                captured: dict = {}

                def fake_invoke(state):
                    captured["data"] = growth_agent.get_store().load().data
                    return {"user_skills": [], "growth_diff": {}}

                with mock.patch.object(analyze_mod.workflow, "invoke", side_effect=fake_invoke):
                    analyze_mod.run_workflow(_payload(), baseline_store=user_store)

                seen = _fingerprints(captured["data"])
                self.assertIn("user1\t技能\t证据", seen, "隔离基线应是传入的用户 store")
                self.assertNotIn("decoy\t旧全局\t数据", seen, "不得再从全局默认 store 拿基线")
            finally:
                growth_agent.set_store(previous)

    def test_without_baseline_falls_back_to_global_default(self):
        """不传 baseline_store：行为与旧口径一致（全局默认 store 提供基线）。"""
        with tempfile.TemporaryDirectory() as tmp:
            global_store = GrowthStore(directory=Path(tmp) / "global")
            global_store.append({
                "events": [{"fingerprint": "global\t默认\t基线"}],
                "user_skills_after": [],
            })

            import backend.analyze as analyze_mod

            previous = growth_agent._store
            growth_agent.set_store(global_store)
            try:
                captured: dict = {}

                def fake_invoke(state):
                    captured["data"] = growth_agent.get_store().load().data
                    return {"user_skills": [], "growth_diff": {}}

                with mock.patch.object(analyze_mod.workflow, "invoke", side_effect=fake_invoke):
                    analyze_mod.run_workflow(_payload())

                self.assertIn("global\t默认\t基线", _fingerprints(captured["data"]))
            finally:
                growth_agent.set_store(previous)


class AnalyzeAndSaveBaselineTest(unittest.TestCase):
    """run_analyze_and_save 用请求自带的 stores.growth 当基线（接线正确性）。"""

    def test_baseline_is_the_request_users_growth_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stores = services.Stores(
                growth=GrowthStore(directory=root / "g"),
                loop=LoopStore(directory=root / "l"),
            )
            seen: dict = {}

            def fake_run_workflow(payload, baseline_store=None):
                seen["baseline"] = baseline_store
                return {"learning_plan": [{"topic": "t", "covers": []}], "project_plan": []}

            with mock.patch("backend.analyze.run_workflow", side_effect=fake_run_workflow):
                result = services.run_analyze_and_save(stores, _payload())

            self.assertIs(seen["baseline"], stores.growth,
                          "分析并保存的基线必须是本次请求的 growth store")
            self.assertTrue(result["round_created"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
