"""Project Planning Agent：用项目来补齐能力缺口，而不是只推荐"学什么"。"""

from pydantic import BaseModel, Field

from agents.llm import structured_invoke
from agents.utils import check_non_empty, dedupe_by, log
from graph.state import CareerState, check_update

PROMPT = """你是一名技术项目实训导师。请为一名想成为「{target_job}」的大学生
设计实战项目。

【他的能力差距（已按优先级排序）】
{gaps}

【已经为他安排的学习路线】
{learning_plan}

【核心理念】
不要只是告诉他"去学什么"，而是**用项目把能力缺口补上**。
一个设计得好的项目，应该能同时覆盖多个能力缺口。
例如：缺 FastAPI + Docker + Agent 编排，就可以设计一个
"AI 智能求职助手"，要求用 FastAPI 提供接口、用 Agent 编排流程、用 Docker 部署，
一个项目同时补三个缺口。

【要求】
1. 设计 2~3 个项目，难度递进，第 1 个最简单。
2. 每个项目必须同时覆盖**至少 2 项**能力差距，覆盖得越多越好；
   优先覆盖优先级"高"的缺口。
3. covers_gaps 必须使用上面给出的能力差距里的技能原名，一字不差，
   一项技能写完整（写"Agent 与工作流编排"，不要拆成"Agent"、"工作流编排"）。
4. name 只写项目名称本身，短一点、像项目名
   （如"AI 智能求职助手"），不要把阶段号、说明写进名字里。
5. goal 写这个项目要达成什么、补哪些能力，**不要出现"阶段"两个字**；
   阶段信息只写在 stage 字段里，stage 要和上面的学习路线对得上。
6. tech_stack 写这个项目实际会用到的技术，必须包含 covers_gaps 里的技能。
7. deliverable 写最终交付物，要具体可验收，
   例如"一个能跑的 HTTP 服务 + GitHub 仓库 + README 部署说明 + Dockerfile"。
8. 项目要做学生真正能做完的规模，不要设计成企业级系统。
9. 全部用中文，技术名称保留英文原文。"""


class ProjectItem(BaseModel):
    """一个实战项目。"""

    name: str = Field(description="项目名称，短，不含阶段号")
    goal: str = Field(description="项目目标：这个项目做出来是为了补哪些能力，不要写阶段号")
    covers_gaps: list[str] = Field(description="对应的能力缺口，用技能原名")
    tech_stack: list[str] = Field(description="使用的技术栈")
    stage: str = Field(description="项目阶段，对应学习路线的哪个阶段")
    deliverable: str = Field(description="最终成果，要具体可验收")


class ProjectPlan(BaseModel):
    """Project Agent 的结构化输出。"""

    projects: list[ProjectItem] = Field(description="项目列表，难度递进")


def _format_gaps(gaps: list) -> str:
    if not gaps:
        return "（无）"
    return "\n".join(
        f"- {g.get('skill')}｜优先级 {g.get('priority')}｜{g.get('gap')}" for g in gaps
    )


def _format_learning_plan(stages: list) -> str:
    if not stages:
        return "（无）"
    return "\n".join(
        f"- 阶段 {s.get('stage')}：{s.get('topic')}（{s.get('goal')}）" for s in stages
    )


def project_node(state: CareerState) -> dict:
    """LangGraph 节点：读取 skill_gaps / learning_plan，写入 project_plan。"""
    gaps = state.get("skill_gaps") or []
    if not gaps:
        raise ValueError("state 中缺少 skill_gaps，无法设计实战项目")

    prompt = PROMPT.format(
        target_job=state.get("target_job", "目标岗位"),
        gaps=_format_gaps(gaps),
        learning_plan=_format_learning_plan(state.get("learning_plan") or []),
    )
    plan = structured_invoke(prompt, ProjectPlan)

    projects = [p.model_dump() for p in plan.projects]
    projects = dedupe_by(projects, key="name")
    check_non_empty(projects, "Project Agent 的项目列表", minimum=1)

    log("Project Agent")
    return check_update({"project_plan": projects}, "Project Agent")
