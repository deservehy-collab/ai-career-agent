"""LangGraph 全局状态：所有 Agent 共享的数据结构。"""

from typing import TypedDict


class CareerState(TypedDict, total=False):
    # ---- 输入 ----
    user_profile: dict  # 学生个人信息（专业/年级/自述技能/项目经历）
    target_job: str  # 目标岗位
    jd_text: str  # 可选：用户当场粘贴的招聘要求原文，本次岗位要求的唯一依据
    growth_events: list  # 可选：新学习成果 / 新项目经历（阶段五输入），缺省视为无新成果

    # ---- Profile Agent ----
    user_skills: list  # 学生已掌握技能 [{skill, level, evidence}]
    user_strengths: list  # 技术优势
    user_weaknesses: list  # 技术短板

    # ---- Growth Agent（阶段五：动态能力成长）----
    # 注意：user_skills 仍是**唯一**的"当前能力"真源，growth_node 直接更新它；
    # 下面三个是快照/追踪/差异，只供展示与回溯，**不参与任何下游计算**。
    user_skills_before: list  # 本次运行的基线快照（已合并历史成长结果）
    skill_updates: list  # 逐项等级变化 [{skill, from, to, reason, source}]
    growth_diff: dict  # 等级 / 缺口 / 匹配率的前后差异

    # ---- Retrieval Agent（依据整理：只描述岗位要什么，不是学生能力）----
    job_evidence: list  # 岗位要求原文逐句记录 [{skill, note, provenance, source_id, ...}]
    retrieval_status: str  # user_pasted / no_source
    retrieval_diagnostics: dict  # 依据整理诊断：原话句数、过滤掉的短句、空原文原因等

    # ---- Job Agent ----
    job_requirements: list  # 岗位要求 [{skill, importance, level, reason}]

    # ---- Assessment Agent ----
    skill_gaps: list  # 能力差距
    # 模型在 assessment 那一次调用的**原始回答**（未经清洗/过滤/回退）：
    # [{skill, supported_by, gap}]，三个字段原样保存 —— supported_by 允许缺失或为空字符串，
    # 绝不在这里改写成"无"（那是代码判定环节的事）。
    # 用途：阶段五的成长前后缺口对比要用**同一批原始回答**跑两次 judge_gaps。
    assessment_answers: list

    # ---- Learning / Project Agent ----
    learning_plan: list
    project_plan: list

    # ---- 汇总 ----
    final_plan: dict
    # 说明：阶段四的 JD 匹配结论不在这里 —— 工作流没有汇总节点，
    # 它由 build_final_plan() 现算并放进**返回值**的 "jd_match" 里，
    # 不写回 state（写了也没人读）。


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