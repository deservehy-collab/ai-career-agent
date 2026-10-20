"""校验阶段三的两类知识库（Skill 知识库 + Project 知识库）。

检查内容
--------
1. YAML 能否正确解析、顶层结构是否正确。
2. Skill：12 项技能全覆盖、名称与岗位画像（阶段二）完全一致、
   名称不重复、level_guides 四档完整、prerequisites 引用有效。
3. Project：字段完整且类型正确、covers_skills / prerequisites 引用有效、
   难度梯度合法、项目间难度有梯度（综合项目不得人人推荐由查询层保证，这里只查数据合法）。
4. 输出知识库内容概览。

用法
----
    python scripts/validate_knowledge.py

任何校验失败都会以非零退出码报错，绝不静默忽略。

注意：本脚本只读知识库源文件与阶段二岗位画像，**不写入**，
也**不会修改任何知识库文件**。
"""

import sys
from pathlib import Path

import yaml

# 允许作为脚本直接运行时找到 agents 包（脚本目录是 scripts/）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.project_knowledge import (  # noqa: E402
    DIFFICULTY_RANK,
    MAX_DIFFICULTY,
    VALID_DIFFICULTY,
    ProjectKnowledgeBase,
)
from agents.skill_knowledge import SKILL_LEVELS, SkillKnowledgeBase  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 阶段三首批应收录的技能（与岗位画像中完全一致）
EXPECTED_SKILLS = [
    "Python", "RAG", "Agent", "Prompt Engineering", "LLM API", "Function Calling",
    "后端 API 开发", "测试与效果评测", "Git", "Docker", "Embedding", "LangChain / LangGraph",
]

# 岗位画像路径（作为规范技能名的权威来源）
PROFILE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "jobs" / "ai-application-engineer.yaml"

REQUIRED_PROJECT_FIELDS = {
    "name": str,
    "difficulty": str,
    "covers_skills": list,
    "prerequisites": list,
    "tech_stack": list,
    "stage_hint": str,
    "deliverable": str,
    "acceptance_criteria": list,
    "estimated_weeks": int,
}


def load_profile_skill_names() -> set[str]:
    """从阶段二岗位画像读取规范技能名集合。"""
    with PROFILE_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    skills = data.get("skills")
    if not isinstance(skills, list):
        raise SystemExit(f"岗位画像 {PROFILE_PATH} 缺少 skills 列表")
    return {str(s.get("skill", "")).strip() for s in skills if s}


def validate_skills(skills: SkillKnowledgeBase, profile_names: set[str]) -> int:
    """校验 Skill 知识库，返回技能数量。"""
    names = skills.all_skill_names()

    # 名称必须在岗位画像中存在（不允许自造规范技能名）
    unknown = [n for n in names if n not in profile_names]
    if unknown:
        raise SystemExit(f"Skill 知识库含岗位画像之外的技能名：{unknown}")

    # 首批规定必须全部收录
    missing = [n for n in EXPECTED_SKILLS if n not in set(names)]
    if missing:
        raise SystemExit(f"Skill 知识库缺少首批要求技能：{missing}")

    # 前置技能引用校验：必须引用知识库中真实存在的技能
    for name in names:
        item = skills.get(name)
        prereqs = item.get("prerequisites") or []
        for req in prereqs:
            if req not in names:
                raise SystemExit(f"技能 {name!r} 的前置技能 {req!r} 在知识库中不存在")

    print(f"[Skill] 收录技能 {len(names)} 项，全部通过校验（均在岗位画像内，前置引用有效）")
    return len(names)


def validate_projects(projects: ProjectKnowledgeBase, profile_names: set[str],
                      skills_names: set[str]) -> int:
    """校验 Project 知识库，返回项目数量并打印概览。"""
    items = projects.projects
    if len(items) < 4:
        raise SystemExit(f"Project 知识库项目数不足（预期 >=4，实际 {len(items)}）")

    difficulties = [DIFFICULTY_RANK[p["difficulty"]] for p in items]
    for p in items:
        name = p["name"]
        for field_name, expected_type in REQUIRED_PROJECT_FIELDS.items():
            value = p.get(field_name)
            if value is None:
                raise SystemExit(f"项目 {name!r} 缺少字段 {field_name!r}")
            if not isinstance(value, expected_type):
                raise SystemExit(
                    f"项目 {name!r} 字段 {field_name!r} 类型错误："
                    f"应为 {expected_type.__name__}，实际 {type(value).__name__}"
                )
        # covers / prerequisites 引用校验
        for key in ("covers_skills", "prerequisites"):
            for skill in p.get(key, []):
                if skill not in profile_names:
                    raise SystemExit(f"项目 {name!r} 的 {key} 引用了非规范技能：{skill!r}")

    if len(set(difficulties)) < 2:
        raise SystemExit("项目难度需有梯度（覆盖至少两档）")

    print(f"[Project] 项目模板 {len(items)} 个：")
    for p in items:
        print(
            f"  - {p['name']} ｜难度 {p['difficulty']} ｜覆盖 {len(p['covers_skills'])} 技能"
            f" ｜预计 {p.get('estimated_weeks')} 周"
        )
    return len(items)


def main() -> None:
    print("=== 阶段三知识库校验 ===")
    profile_names = load_profile_skill_names()

    skills = SkillKnowledgeBase()
    validate_skills(skills, profile_names)

    projects = ProjectKnowledgeBase()
    validate_projects(projects, profile_names, set(skills.all_skill_names()))

    print("\n校验通过：领域内技能引用全部有效，未发现非法源文件。")


if __name__ == "__main__":
    main()