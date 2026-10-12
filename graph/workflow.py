"""LangGraph 工作流：把各 Agent 串成一条顺序流水线。

START → profile → retrieval → job → assessment → learning → project → END

其中 retrieval 节点只做岗位知识库检索，失败会降级为空证据，不影响后续节点。
"""

from langgraph.graph import END, START, StateGraph

from agents.assessment_agent import assessment_node
from agents.jd_match import compute_jd_match, resolve_target
from agents.job_agent import job_node
from agents.learning_agent import learning_node
from agents.profile_agent import profile_node
from agents.project_agent import project_node
from agents.retrieval_agent import retrieval_node
from graph.state import CareerState

# 节点名 → 处理函数
NODES = {
    "profile": profile_node,
    "retrieval": retrieval_node,
    "job": job_node,
    "assessment": assessment_node,
    "learning": learning_node,
    "project": project_node,
}

# 顺序执行的节点顺序，add_edge 也按这个顺序连
ORDER = ["profile", "retrieval", "job", "assessment", "learning", "project"]


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

    # 阶段四：真实 JD 定向匹配（确定性汇总，复用 job_evidence / skill_gaps）
    jd_target = None
    jd_meta = None
    company_slug = None
    try:
        target = resolve_target(state.get("jd_source_id"), state.get("target_company"))
        jd_target = target["source_id"]
        jd_meta = target["jd_meta"]
        company_slug = target["company_slug"]
    except Exception as exc:  # 入口参数异常已在 retrieval_node 暴露；这里兜底不中断汇总
        print(f"[Final Plan] 警告：真实 JD 匹配目标解析失败，按跨公司概览处理（{type(exc).__name__}: {exc}）", flush=True)
    jd_match = compute_jd_match(
        skill_gaps=gaps,
        job_requirements=state.get("job_requirements") or [],
        evidence=state.get("job_evidence") or [],
        jd_meta=jd_meta,
        jd_target=jd_target,
        company_slug=company_slug,
    )

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
        "jd_match": jd_match,
    }