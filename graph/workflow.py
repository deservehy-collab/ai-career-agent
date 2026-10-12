"""LangGraph 工作流：把各 Agent 串成一条顺序流水线。

START → profile → growth → retrieval → job → assessment → learning → project → END

- retrieval 节点只做岗位知识库检索，失败会降级为空证据，不影响后续节点。
- growth 节点紧跟 profile：能力必须先按本轮成长事件更新完，后面的检索、岗位匹配、
  能力评估、学习与项目规划才会按**新能力**重算。没有成长事件时它不升级任何等级，
  能力表等于"合并历史后的基线"（历史为空时就是 profile 的原样输出）。
"""

from types import SimpleNamespace

from langgraph.graph import END, START, StateGraph

from agents.assessment_agent import assessment_node
from agents.growth_agent import compare_growth_gaps, growth_node
from agents.jd_match import compute_jd_match, resolve_target
from agents.job_agent import job_node
from agents.learning_agent import learning_node
from agents.profile_agent import profile_node
from agents.project_agent import project_node
from agents.retrieval_agent import retrieval_node
from agents.retriever import SkillVocabulary
from graph.state import CareerState

# 节点名 → 处理函数
NODES = {
    "profile": profile_node,
    "growth": growth_node,
    "retrieval": retrieval_node,
    "job": job_node,
    "assessment": assessment_node,
    "learning": learning_node,
    "project": project_node,
}

# 顺序执行的节点顺序，add_edge 也按这个顺序连
ORDER = ["profile", "growth", "retrieval", "job", "assessment", "learning", "project"]


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


def _load_vocabulary() -> SkillVocabulary | None:
    """取技能词表用于缺口配对。不可用时返回 None，配对退回"小写去空格"的兜底键。

    汇总阶段不该因为读不到知识库文件就报错 —— 配对键两侧同源（都来自 job_requirements
    的 skill 原文），兜底键一样能对上，只是少了别名归并。
    """
    try:
        return SkillVocabulary()
    except Exception:  # noqa: BLE001 - 汇总阶段的降级路径
        return None


def _rebuild_analysis(answers: list):
    """把 ``assessment_answers`` 重建成本模块所需的最小 analysis 对象。

    只回填 ``judge_gaps`` 真正读取的三个字段。``supported_by`` 缺失或为空时补成**空字符串**
    —— 空串会走"学生表里查不到 → 无"的既有路径，与"模型没给出支撑"语义一致；
    这里**不写 "无"**（"无"是 judge_gaps 的判定结果，不是模型的原始回答）。
    """
    return SimpleNamespace(gaps=[
        SimpleNamespace(
            skill=item.get("skill"),
            supported_by=str(item.get("supported_by") or ""),
            gap=item.get("gap"),
        )
        for item in answers
    ])


def _growth_block(state: dict):
    """把成长前后的岗位缺口对比并进 ``state`` 里已有的 ``growth_diff``。

    没有成长上下文（阶段一~四那种不跑 growth 节点的运行）时返回 ``None``：
    那样 ``final_plan`` 一个键都不多，旧输出逐字段不变。

    对比要求：**同一批岗位要求 + 同一批模型原始回答**，只有技能快照不同。
    拿不到原始回答时交给 compare_growth_gaps 明确报"不可比较"，
    **不拿空回答硬算**（那会退化成"只比同名技能"，看起来像结论其实不是）。
    """
    if not (state.get("growth_diff") or state.get("user_skills_before")):
        return None

    raw_answers = state.get("assessment_answers") or []
    comparison = compare_growth_gaps(
        state.get("user_skills_before") or [],
        state.get("user_skills") or [],
        state.get("job_requirements") or [],
        _rebuild_analysis(raw_answers) if raw_answers else None,
        _load_vocabulary(),
    )

    block = dict(state.get("growth_diff") or {})
    block["gap_comparison"] = comparison
    block["gap_changes"] = comparison.get("changes", [])
    block["newly_satisfied"] = comparison.get("newly_satisfied", [])
    block["newly_appeared"] = comparison.get("newly_appeared", [])
    block["resolved_gaps"] = comparison.get("resolved_gaps", [])
    return block


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

    plan = {
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

    # 阶段五：有成长上下文时补上"成长前后缺口变化"。没有成长上下文就不加这个键 ——
    # 阶段一~四的运行输出因此逐字段保持原样。
    growth = _growth_block(state)
    if growth is not None:
        plan["growth_diff"] = growth

    return plan