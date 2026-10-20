"""agents/project_knowledge.py 的单元测试（标准库 unittest）。

隔离策略：用临时目录写入受控的 YAML，不触碰真实知识库。
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from agents import project_knowledge as PK  # noqa: E402


def _project(name, difficulty, covers, skills=None, prereq=None):
    return {
        "name": name,
        "difficulty": difficulty,
        "covers_skills": covers,
        "prerequisites": prereq or [],
        "tech_stack": skills or ["Python"],
        "stage_hint": "中段",
        "deliverable": f"{name} 交付物",
        "acceptance_criteria": ["可运行"],
        "estimated_weeks": 2,
    }


def _make_base(tmp: Path, projects: list):
    for i, p in enumerate(projects):
        (tmp / f"p{i}.yaml").write_text(yaml.safe_dump(p, allow_unicode=True), encoding="utf-8")
    return PK.ProjectKnowledgeBase(directory=tmp)


EASY = _project("A", "beginner", ["Python"], skills=["Python"])
MID = _project("B", "intermediate", ["Python", "RAG"], skills=["Python", "LangChain"])
HARD = _project("C", "advanced", ["Python", "RAG", "Agent", "后端 API 开发", "Docker"],
                skills=["Python", "FastAPI", "LangGraph", "Docker"])


class TestProjectKnowledge(unittest.TestCase):
    def test_load_and_get(self):
        with tempfile.TemporaryDirectory() as d:
            base = _make_base(Path(d), [EASY, MID])
        self.assertIsNotNone(base.get("A"))
        self.assertIsNone(base.get("不存在"))

    def test_recommend_prefers_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            base = _make_base(Path(d), [EASY, MID, HARD])
        # 缺 RAG：应优先覆盖 RAG 的中间项目
        recs = base.recommend(["Python", "RAG"])
        self.assertGreaterEqual(len(recs), 1)
        self.assertEqual(recs[0]["name"], "B")
        # covers_skills 里确实包含 RAG 才允许排前
        self.assertIn("RAG", recs[0]["covers_skills"])

    def test_recommend_filters_beyond_max_difficulty(self):
        with tempfile.TemporaryDirectory() as d:
            base = _make_base(Path(d), [EASY, MID, HARD])
        # 学生刚起步（beginner）：高级综合项目应被排除
        recs = base.recommend(["Python", "RAG", "Agent", "后端 API 开发"], max_difficulty="beginner")
        names = [r["name"] for r in recs]
        self.assertNotIn("C", names)
        self.assertIn("A", names)

    def test_recommend_unknown_skills_no_crash(self):
        with tempfile.TemporaryDirectory() as d:
            base = _make_base(Path(d), [EASY])
        recs = base.recommend(["完全不存在的技能"])
        self.assertIsInstance(recs, list)

    def test_invalid_difficulty_raises(self):
        bad = dict(EASY)
        bad["difficulty"] = "godlike"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "p.yaml").write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
            with self.assertRaises(PK.ProjectKnowledgeError):
                PK.ProjectKnowledgeBase(directory=Path(d))

    def test_missing_field_raises(self):
        bad = dict(EASY)
        bad.pop("acceptance_criteria")
        # 用非 list 类型触发校验失败
        bad["acceptance_criteria"] = "not-a-list"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "p.yaml").write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
            with self.assertRaises(PK.ProjectKnowledgeError):
                PK.ProjectKnowledgeBase(directory=Path(d))

    def test_duplicate_project_name_raises(self):
        with tempfile.TemporaryDirectory() as d:
            _make_base(Path(d), [EASY])  # 写一个名为 A 的项目
            # 再写一个同名 A，应触发重复校验
            (Path(d) / "dup.yaml").write_text(
                yaml.safe_dump(dict(EASY), allow_unicode=True), encoding="utf-8"
            )
            with self.assertRaises(PK.ProjectKnowledgeError):
                PK.ProjectKnowledgeBase(directory=Path(d))


if __name__ == "__main__":
    unittest.main()