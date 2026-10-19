"""请求体输入上限（backend/schemas.py）。

动机：loop.json 是全量读-改-写的，任何无界写入都会拖慢所有人的后续查询。
manual-event 此前没有 title/skills 上限，且证据上限与任务完成口径不一致
（这里统一成同一个 EvidenceText：5000 字）。growth_events 与 target_job
也补上数量/长度上限。

直接对 Pydantic 模型断言，不需要起 HTTP 栈。
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from backend import config  # noqa: E402
from backend.schemas import (  # noqa: E402
    AnalyzeRequest, ManualGrowthEventRequest,
)


def _manual(**overrides) -> dict:
    base = {"kind": "learning", "title": "自学了 Git", "evidence": "推到了远程仓库"}
    base.update(overrides)
    return base


class ManualEventLimitTest(unittest.TestCase):
    def test_accepts_normal_payload(self):
        parsed = ManualGrowthEventRequest(**_manual(skills=["Git", " Python "]))
        self.assertEqual(parsed.title, "自学了 Git")
        self.assertEqual(parsed.skills, ["Git", "Python"], "技能名应去首尾空白")

    def test_title_over_limit_rejected(self):
        with self.assertRaises(ValidationError):
            ManualGrowthEventRequest(**_manual(title="长" * (config.MANUAL_TITLE_MAX_CHARS + 1)))

    def test_too_many_skills_rejected(self):
        skills = [f"skill{i}" for i in range(config.MANUAL_SKILLS_MAX_ITEMS + 1)]
        with self.assertRaises(ValidationError):
            ManualGrowthEventRequest(**_manual(skills=skills))

    def test_evidence_shares_the_task_evidence_limit(self):
        with self.assertRaises(ValidationError):
            ManualGrowthEventRequest(**_manual(evidence="长" * (config.EVIDENCE_MAX_LENGTH + 1)))
        # 空白证据同样拒绝（EvidenceText 先 strip 再验长度）
        with self.assertRaises(ValidationError):
            ManualGrowthEventRequest(**_manual(evidence="   \n\t "))


class AnalyzeRequestLimitTest(unittest.TestCase):
    def _profile(self) -> dict:
        return {"major": "软件工程", "grade": "大三", "skills": ["Python"], "projects": []}

    def test_growth_events_count_capped(self):
        events = [{"type": "learning", "title": f"t{i}"} for i in range(config.GROWTH_EVENTS_MAX_ITEMS + 1)]
        with self.assertRaises(ValidationError):
            AnalyzeRequest(user_profile=self._profile(), target_job="软件工程师", growth_events=events)
        ok = AnalyzeRequest(user_profile=self._profile(), target_job="软件工程师", growth_events=events[:-1])
        self.assertEqual(len(ok.growth_events), config.GROWTH_EVENTS_MAX_ITEMS)

    def test_target_job_length_capped(self):
        with self.assertRaises(ValidationError):
            AnalyzeRequest(user_profile=self._profile(),
                           target_job="岗" * (config.TARGET_JOB_MAX_CHARS + 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
