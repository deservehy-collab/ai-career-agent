"""Profile Agent：分析学生个人信息，输出结构化技能画像。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from agents.llm import structured_invoke
from agents.utils import check_non_empty, dedupe_by, log, normalize_level
from graph.state import CareerState, check_update

PROMPT = """你是一名资深技术职业规划师。请分析下面这名大学生的个人信息，
提取他已掌握的技能、技能水平，以及技术优势和技术短板。

【学生信息】
专业：{major}
年级：{grade}
自述技能：{skills}
项目经历：{projects}

【评级标准】必须严格按证据分级，不要因为技能出现在自述里就给高分：
- 入门：只是听说过或跟着教程跑过示例，说不清原理
- 初级：能在指导下完成简单任务，不熟常见坑
- 中级：能独立完成常规开发任务，遇到问题能自己查资料解决
- 高级：能主导设计、做过优化或踩坑总结，能讲清底层原理

【要求】
1. 只能依据上面给出的信息判断，不要虚构学生没有的经历和技能。
2. level 只能从这四档里选：入门、初级、中级、高级。
3. 如果某项技能只出现在"自述技能"里、没有任何项目经历佐证，最高只能给"中级"。
4. evidence 要写明判断依据，例如"在 RAG 知识库问答系统中实际使用过"；
   依据相同也不要机械复制同一句话，要结合该技能本身说明。
5. strengths 给 2~4 条技术优势，weaknesses 给 2~4 条技术短板，每条一句话。
   短板要具体到技术能力（如"缺少后端服务开发经验"），不要写"需加强项目管理"这类空话。
6. 全部用中文。"""


class Skill(BaseModel):
    """单个技能的画像。"""

    skill: str = Field(description="技能名称，如 Python、LangGraph")
    level: Literal["入门", "初级", "中级", "高级"] = Field(description="掌握水平")
    evidence: str = Field(description="判断依据，来自自述或项目经历")

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_level(cls, value):
        # 小模型常常冒出"熟练掌握"这类说法，先归一化再交给 Literal 校验
        return normalize_level(value)


class ProfileAnalysis(BaseModel):
    """Profile Agent 的结构化输出。"""

    skills: list[Skill] = Field(description="学生已掌握的技能列表")
    strengths: list[str] = Field(description="技术优势")
    weaknesses: list[str] = Field(description="技术短板")


def profile_node(state: CareerState) -> dict:
    """LangGraph 节点：读取 user_profile，写入 user_skills / strengths / weaknesses。"""
    profile = state.get("user_profile") or {}
    if not profile:
        raise ValueError("state 中缺少 user_profile，无法分析学生能力")

    prompt = PROMPT.format(
        major=profile.get("major", "未知"),
        grade=profile.get("grade", "未知"),
        skills="、".join(profile.get("skills") or []) or "无",
        projects="、".join(profile.get("projects") or []) or "无",
    )

    analysis = structured_invoke(prompt, ProfileAnalysis)

    # 同一个技能可能被模型重复列出，去重后再交给下游
    skills = dedupe_by([s.model_dump() for s in analysis.skills], key="skill")
    check_non_empty(skills, "Profile Agent 的技能列表")

    log("Profile Agent")
    return check_update(
        {
            "user_skills": skills,
            "user_strengths": analysis.strengths,
            "user_weaknesses": analysis.weaknesses,
        },
        "Profile Agent",
    )
