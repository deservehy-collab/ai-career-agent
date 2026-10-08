"""Job Analysis Agent：把目标岗位拆解成结构化的技能要求。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from agents.llm import structured_invoke
from agents.utils import check_non_empty, dedupe_by, log, normalize_level
from graph.state import CareerState, check_update

PROMPT = """你是一名资深技术招聘专家。请分析「{job}」这个岗位，
拆解出这个岗位真正要求的核心技能。

【岗位定位】先分清这个岗位属于哪一类，再据此拆解：
- 如果是"大模型 / AI 应用开发"类岗位：它是把大模型能力落地成产品的**工程岗**，
  不是训练模型的算法岗。此时下列方向**每一类都必须至少覆盖一项**，缺一不可：
  ① 编程语言        （如 Python）
  ② 大模型调用与提示词工程（如 LLM API、Prompt Engineering）
  ③ Agent 与工作流编排    （如 Agent、LangChain、LangGraph、Function Calling，
                           RAG 不能算作这一项，必须单独出现）
  ④ RAG 检索增强         （如 Embedding、向量数据库）
  ⑤ 后端服务            （如 FastAPI）
  ⑥ 工程化与部署         （如 Docker、Git）
  在此基础上再补充该岗位会考察的其他技能，不要用 PyTorch、深度学习理论顶替上面这些。
- 如果是算法 / 研究类岗位：才以机器学习、深度学习框架、数学基础为核心。

【要求】
1. 给出 6~10 项核心技能，覆盖编程语言、框架、工程能力、计算机基础等不同层面。
2. 只列这个岗位真正会考察的技能，不要凑数。
3. importance 是 1~5 的整数，5 表示最重要。必须有区分度，
   不要把每项都写成 5，最多 2 项可以是 5。
4. level 是该岗位对这项技能的推荐能力等级（入门/初级/中级/高级）。
5. reason 用一句话说明这项技能在岗位里具体用来做什么。
6. 全部用中文，技能名称保留英文原文（如 Python、FastAPI、Docker）。"""


class JobRequirement(BaseModel):
    """岗位对单项技能的要求。"""

    skill: str = Field(description="技能名称")
    importance: int = Field(description="重要程度，1~5 的整数，5 最重要")
    level: Literal["入门", "初级", "中级", "高级"] = Field(description="岗位要求的推荐能力等级")
    reason: str = Field(description="这项技能在岗位中的用途")

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_level(cls, value):
        return normalize_level(value)


class JobAnalysis(BaseModel):
    """Job Agent 的结构化输出。"""

    requirements: list[JobRequirement] = Field(description="岗位核心技能要求列表")


def job_node(state: CareerState) -> dict:
    """LangGraph 节点：读取 target_job，写入 job_requirements（按重要程度降序）。"""
    target_job = (state.get("target_job") or "").strip()
    if not target_job:
        raise ValueError("state 中缺少 target_job，无法分析岗位要求")

    analysis = structured_invoke(PROMPT.format(job=target_job), JobAnalysis)

    requirements = []
    for req in analysis.requirements:
        item = req.model_dump()
        # 小模型偶尔会给出越界的 importance，这里兜一下底
        item["importance"] = max(1, min(5, item["importance"]))
        requirements.append(item)

    # 模型经常把同一个技能列两遍（如 Git），去重后再排序
    requirements = dedupe_by(requirements, key="skill")
    check_non_empty(requirements, "Job Agent 的岗位技能列表", minimum=3)

    # 按重要程度降序，方便后续 Agent 优先处理关键缺口
    requirements.sort(key=lambda r: r["importance"], reverse=True)

    log("Job Agent")
    return check_update({"job_requirements": requirements}, "Job Agent")
