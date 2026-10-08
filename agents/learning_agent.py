"""Learning Planning Agent：根据 skill_gaps 制定学习路线。"""

from pydantic import BaseModel, Field

from agents.llm import structured_invoke
from agents.utils import check_non_empty, dedupe_by, log
from graph.state import CareerState, check_update

PROMPT = """你是一名技术学习路径规划师。请为一名想成为「{target_job}」的大学生
安排一条学习路线。

【他的能力差距（已按优先级排序）】
{gaps}

【他目前已有的技能】
{user_skills}

【要求】
1. 只针对上面**优先级为"高"或"中"**的缺口安排学习，不要给"低"的缺口排期。
2. 一共安排 3~5 个阶段。**不要贪多**，不要把所有技术都塞进来，
   宁可少而深。同一个阶段内可以合并相关性强的技能。
3. 严格按学习的前置关系排序：必须先学的基础排在前面，
   （例如先有 Python 基础再学后端框架，先会后端再学部署）。
4. 优先级"高"的缺口必须排在更靠前的阶段，不能被低优先级技能挤到后面。
5. 每个阶段要说清楚：
   - goal：为什么要学这个、它解决哪个能力缺口；
   - covers：这一阶段覆盖了上面哪几项差距。
     **只写技能名本身**，必须和上面给出的技能名一字不差，
     不要加括号、等级或任何修饰（写"LLM API"，不要写"LLM API（高级）"）；
   - prerequisite：学之前需要具备什么（参考他已有的技能）；
   - completion_criteria：达到什么程度算学会，要可验证，
     例如"能独立开发一个提供 3 个接口的 AI 服务并写清 README"，
     不要写"掌握 FastAPI"这种没法验收的话；
   - estimated_weeks：预计需要几周，填整数。
6. 全部用中文，技术名称保留英文原文。"""


class LearningStage(BaseModel):
    """一个学习阶段。"""

    stage: int = Field(description="阶段序号，从 1 开始")
    topic: str = Field(description="这一阶段学什么")
    goal: str = Field(description="为什么学，解决哪个能力缺口")
    covers: list[str] = Field(description="覆盖的能力差距，用技能原名")
    prerequisite: str = Field(description="前置要求")
    completion_criteria: str = Field(description="完成标准，必须可验证")
    estimated_weeks: int = Field(description="预计周数")


class LearningPlan(BaseModel):
    """Learning Agent 的结构化输出。"""

    stages: list[LearningStage] = Field(description="学习阶段列表")


def _format_gaps(gaps: list) -> str:
    if not gaps:
        return "（无）"
    return "\n".join(
        f"- {g.get('skill')}｜优先级 {g.get('priority')}｜岗位重要度 {g.get('importance')}｜"
        f"当前 {g.get('current_level')}，要求 {g.get('required_level')}｜{g.get('gap')}"
        for g in gaps
    )


def _format_skills(skills: list) -> str:
    if not skills:
        return "（无）"
    return "、".join(f"{s.get('skill')}（{s.get('level')}）" for s in skills)


def learning_node(state: CareerState) -> dict:
    """LangGraph 节点：读取 skill_gaps / user_skills / target_job，写入 learning_plan。"""
    gaps = state.get("skill_gaps") or []
    if not gaps:
        raise ValueError("state 中缺少 skill_gaps，无法制定学习路线")

    prompt = PROMPT.format(
        target_job=state.get("target_job", "目标岗位"),
        gaps=_format_gaps(gaps),
        user_skills=_format_skills(state.get("user_skills") or []),
    )
    plan = structured_invoke(prompt, LearningPlan)

    stages = [s.model_dump() for s in plan.stages]
    stages = dedupe_by(stages, key="topic")
    check_non_empty(stages, "Learning Agent 的学习阶段列表", minimum=2)

    # 按阶段号排序，防止模型乱序输出
    stages.sort(key=lambda s: s["stage"])
    for index, stage in enumerate(stages, start=1):
        stage["stage"] = index  # 阶段号重排，保证连续

    log("Learning Agent")
    return check_update({"learning_plan": stages}, "Learning Agent")
