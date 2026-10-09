"""LangGraph 全局状态：所有 Agent 共享的数据结构。"""

from typing import TypedDict


class CareerState(TypedDict, total=False):
    # ---- 输入 ----
    user_profile: dict  # 学生个人信息（专业/年级/自述技能/项目经历）
    target_job: str  # 目标岗位
    target_company: str  # 可选：限定岗位知识库检索的公司（不填则按跨公司概览检索）

    # ---- Profile Agent ----
    user_skills: list  # 学生已掌握技能 [{skill, level, evidence}]
    user_strengths: list  # 技术优势
    user_weaknesses: list  # 技术短板

    # ---- Retrieval Agent（RAG 岗位知识库，只描述岗位，不是学生能力）----
    job_evidence: list  # 检索到的岗位证据 [{company_slug, skill, requirement_type, context, note, ...}]
    retrieval_status: str  # matched / not_mentioned / no_source / ambiguous
    retrieval_diagnostics: dict  # 检索诊断：命中路径、样本范围、失败原因等

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
