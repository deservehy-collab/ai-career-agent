"""LangGraph 工作流：把五个 Agent 串成一条顺序流水线。

START → profile → job → assessment → learning → project → END
"""

from langgraph.graph import END, START, StateGraph

from agents.assessment_agent import assessment_node
from agents.job_agent import job_node
from agents.learning_agent import learning_node
from agents.profile_agent import profile_node
from agents.project_agent import project_node
from graph.state import CareerState

# 节点名 → 处理函数
NODES = {
    "profile": profile_node,
    "job": job_node,
    "assessment": assessment_node,
    "learning": learning_node,
    "project": project_node,
}

# 顺序执行的节点顺序，add_edge 也按这个顺序连
ORDER = ["profile", "job", "assessment", "learning", "project"]


def build_workflow():
    """构建并编译顺序工作流。"""
    builder = StateGraph(CareerState)

    for name, node in NODES.items():
        builder.add_node(name, node)

    builder.add_edge(START, ORDER[0])
    for current, following in zip(ORDER, ORDER[1:]):
        builder.add_edge(current, following)
    builder.add_edge(ORDER[-1], END)

    return builder.compile()


# 模块级编译一次，main.py 直接 import 使用
workflow = build_workflow()


def build_final_plan(state: dict) -> dict:
    """把各 Agent 的产出汇总成最终方案。

    图在 project 之后就结束了（没有额外的汇总节点），
    所以这里用确定性的代码汇总，不再多调一次 LLM。
    """
    gaps = state.get("skill_gaps") or []
    stages = state.get("learning_plan") or []
    projects = state.get("project_plan") or []

    return {
        "target_job": state.get("target_job", ""),
        "already_satisfied": [g["skill"] for g in gaps if g["status"] == "已满足"],
        "top_gaps": [g["skill"] for g in gaps if g["priority"] == "高"][:3],
        "learning_stage_count": len(stages),
        "recommended_projects": [p["name"] for p in projects],
        "next_action": (
            f"从「{stages[0]['topic']}」开始，完成后按完成标准自测"
            if stages
            else "先补齐岗位要求中最关键的技能"
        ),
    }
