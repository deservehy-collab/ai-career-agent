"""LangGraph 全局状态：所有 Agent 共享的数据结构。"""

from typing import TypedDict


class CareerState(TypedDict, total=False):
    # ---- 输入 ----
    user_profile: dict  # 学生个人信息（专业/年级/自述技能/项目经历）
    target_job: str  # 目标岗位

    # ---- Profile Agent ----
    user_skills: list  # 学生已掌握技能 [{skill, level, evidence}]
    user_strengths: list  # 技术优势
    user_weaknesses: list  # 技术短板

    # ---- Job Agent ----
    job_requirements: list  # 岗位要求 [{skill, importance, level, reason}]

    # ---- Assessment Agent ----
    skill_gaps: list  # 能力差距

    # ---- Learning / Project Agent ----
    learning_plan: list
    project_plan: list

    # ---- 汇总 ----
    final_plan: dict


def check_update(update: dict, agent_name: str) -> dict:
    """校验 Agent 返回的字段都在 CareerState 里定义过。

    LangGraph 遇到未定义的 key 会直接报错，提前在这里拦下来，
    报错信息能直接指出是哪个 Agent 写错了字段。
    """
    unknown = sorted(set(update) - set(CareerState.__annotations__))
    if unknown:
        raise ValueError(
            f"{agent_name} 返回了 CareerState 中未定义的字段：{unknown}；"
            f"已定义的字段：{sorted(CareerState.__annotations__)}"
        )
    return update
