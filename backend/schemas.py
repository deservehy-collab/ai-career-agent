"""请求 / 响应模型。

字段命名与 ``graph/state.py`` 的 ``CareerState`` 对齐，前端可以直接把它们
塞进 ``workflow.invoke``。画像**不做后端持久化** —— 由前端 localStorage 保存，
每次请求携带（见 :class:`AnalyzeRequest`）。

被测试锁定的两个模型（不要改字段名）：
- :class:`AnalyzeRequest` —— tests/test_readonly_boundary.py 直接构造
- :class:`CompleteTaskRequest` —— tests/test_growth_loop_api.py 校验 422 行为
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from backend import config

__all__ = [
    "UserProfileRequest", "AnalyzeRequest", "CompleteTaskRequest",
    "NextRoundRequest", "ManualGrowthEventRequest", "EvidenceText",
]


class UserProfileRequest(BaseModel):
    """学生个人信息。等价于 ``CareerState["user_profile"]`` 的四字段。"""

    major: str = Field(default="", description="专业")
    grade: str = Field(default="", description="年级")
    skills: list[str] = Field(default_factory=list, description="自述技能")
    projects: list[str] = Field(default_factory=list, description="项目经历")


# 证据文本：先去掉首尾空白，再校验长度。
# 顺序很重要 —— 先 strip 才能让 "   " / "\n\t" 这类纯空白被判为空而拒绝（422），
# 否则它们会以"长度 3"混过 min_length 检查，被原样写进 loop.json。
EvidenceText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=config.EVIDENCE_MAX_LENGTH,
    ),
]

# 手动补录成果（/api/growth/manual-event）的字段上限。动机与证据文本同款：
# loop.json 是全量读-改-写的，任何无界写入都会拖慢所有人的后续查询。
ManualEventTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=config.MANUAL_TITLE_MAX_CHARS),
]
ManualSkill = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=config.MANUAL_SKILL_MAX_CHARS),
]


class AnalyzeRequest(BaseModel):
    """``POST /api/analyze`` 的请求体。

    对应 ``workflow.invoke`` 的输入：画像 + 目标岗位 + 可选成长事件。
    阶段四的可选入口目标（``target_company`` / ``jd_source_id``）只在传了值时才
    写进 state —— 不传时保持阶段二以来「跨公司概览」的默认行为，逐字段不变。
    """

    user_profile: UserProfileRequest
    target_job: str = Field(
        min_length=1, max_length=config.TARGET_JOB_MAX_CHARS, description="目标岗位，不能为空"
    )
    growth_events: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=config.GROWTH_EVENTS_MAX_ITEMS,
        description="本轮新完成的学习/项目成果；直接透传给 growth_node，由业务层校验",
    )
    target_company: str | None = Field(default=None, description="限定公司（可选）")
    jd_source_id: str | None = Field(default=None, description="精确匹配某份真实 JD（可选，优先级最高）")

    def to_state(self) -> dict:
        """转成 ``CareerState`` 的输入子集。"""
        state: dict = {
            "user_profile": self.user_profile.model_dump(),
            "target_job": self.target_job,
            "growth_events": [dict(item) for item in self.growth_events],
        }
        if self.target_company:
            state["target_company"] = self.target_company
        if self.jd_source_id:
            state["jd_source_id"] = self.jd_source_id
        return state


class CompleteTaskRequest(BaseModel):
    """``POST /api/tasks/{task_id}/complete`` 的请求体。"""

    evidence: EvidenceText = Field(description="完成证据：具体做了什么、有什么产出")
    profile_skills: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "可选：最近一次分析得到的能力表，用于让「升级预览」与下一轮 growth_node "
            "使用同一基线（见 agents/growth_loop.py 的 _evaluate_event）。"
            "不传则退回成长历史基线，预览会比真实判定更严格。"
        ),
    )


class NextRoundRequest(BaseModel):
    """``POST /api/growth/next-round`` 的请求体（整体可选）。

    测试以**无 body** 的方式触发该接口（tests/test_growth_next_round.py），
    所以整份 body 必须可缺省；缺省时由服务层从 ``loop.json`` 的最近一轮取
    ``target_job``，画像则退化为空 —— 那样 profile 节点会明确报错并使该次
    run 标记为 failed，**不会伪造出一轮计划**。
    """

    user_profile: UserProfileRequest | None = None
    target_job: str | None = Field(default=None, max_length=config.TARGET_JOB_MAX_CHARS)


class ManualGrowthEventRequest(BaseModel):
    """``POST /api/growth/manual-event`` 的请求体：手动补录一条成长成果。

    用于打破"空系统死锁"：全新用户还没有任何任务时，也可以直接提交一条
    自己学过/做过的成果，让「生成下一轮」有内容可处理。

    字段上限与任务证据同一套口径（evidence 直接复用 :data:`EvidenceText`，
    也是 5000 字）—— loop.json 是全量读-改-写的，无界写入会拖慢所有后续查询。
    """

    kind: str = Field(description="成果类型，learning|project")
    title: ManualEventTitle = Field(description="成果标题")
    skills: list[ManualSkill] = Field(
        default_factory=list,
        max_length=config.MANUAL_SKILLS_MAX_ITEMS,
        description="成果关联技能",
    )
    evidence: EvidenceText = Field(description="成果证据（具体学了/做了什么）")
    target_job: str | None = Field(default=None, max_length=config.TARGET_JOB_MAX_CHARS, description="目标岗位（可选，首次建任务时用）")