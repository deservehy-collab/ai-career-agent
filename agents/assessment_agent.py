"""Assessment Agent：比对 user_skills 与 job_requirements，产出 skill_gaps。

设计要点（都是为了让 3B 小模型不出错）：
1. 模型只负责"语义对应"——学生会的 LangGraph 算不算岗位要的"Agent 与工作流编排"。
2. 等级、状态、优先级这些算术判断全部由代码算，小模型做序数比较非常不可靠。
3. 学生的水平只能从 Profile Agent 的原数据里查，不允许模型自己评定，
   否则模型会把学生没学过的技能（如 FastAPI）直接判成"已掌握"。
4. supported_by 的取值用动态枚举约束成「学生已有的技能名 + 无」，让模型选不出格。
5. 名字完全一致的直接由代码匹配，不问模型。
"""

from typing import Literal

from pydantic import BaseModel, Field, create_model, field_validator

from agents.llm import structured_invoke
from agents.utils import log, normalize_level
from graph.state import CareerState, check_update

PROMPT = """你是一名技术能力评估专家。请判断学生的已有技能能否支撑目标岗位的要求。

【学生已掌握技能】
{user_skills}

【目标岗位要求】
{job_requirements}

【任务】对上面【目标岗位要求】里的**每一项**，选出学生已有的**哪一项技能**最能支撑它。

【规则】
1. 必须逐项覆盖，不能遗漏，输出条数要和岗位要求条数完全一致。
2. skill 照抄岗位要求里的技能名称原文，一个字都不要改。
3. supported_by 只能从这几个里选一个：{skill_options}，或者填"无"。
   - 名字完全一样的，直接选它（岗位要 Python，学生有 Python，就选 Python）。
   - 名字不一样的，按语义判断（岗位要"Agent 与工作流编排"，学生有 LangGraph，就选 LangGraph）。
   - 一项要求能被学生多个技能支撑时，选**掌握程度最高**的那个。
   - 只有当学生这些技能确实都跟该要求不沾边时，才填"无"。
4. required_level 照抄岗位要求里给的等级。这是**岗位要求**的水平，不是学生水平。
5. gap 描述**学生缺什么**、接下来要补什么，不要描述学生已经会什么。
6. 全部用中文。"""

_LEVEL_RANK = {"无": 0, "入门": 1, "初级": 2, "中级": 3, "高级": 4}
_ALREADY_CLAIMS = ("已掌握", "已具备", "已经掌握", "掌握了", "已有")


def _norm_name(name) -> str:
    """技能名归一化，用于和岗位要求对号（忽略空格和大小写）。"""
    return str(name or "").strip().lower().replace(" ", "")


def _judge_status(current_level: str, required_level: str) -> str:
    """已满足 / 部分满足 / 明显不足。"""
    diff = _LEVEL_RANK[required_level] - _LEVEL_RANK[current_level]
    if diff <= 0:
        return "已满足"
    if diff == 1:
        return "部分满足"
    return "明显不足"


def _judge_priority(status: str, importance: int) -> str:
    """缺口优先级：高 / 中 / 低。"""
    if status == "已满足":
        return "低"
    if status == "明显不足":
        if importance >= 4:
            return "高"
        return "中" if importance == 3 else "低"
    # 部分满足
    return "中" if importance >= 4 else "低"


def _clean_gap_text(text: str, status: str, current_level: str, required_level: str) -> str:
    """校正差距描述与代码算出来的结论的矛盾。

    模型经常写出和数据打架的话，例如：
    - 学生明明是"无"，却写"学生已掌握 FastAPI，需要提升到高级"；
    - 岗位要求"中级"，却写"提升到高级"；
    - 已经"已满足"了，还写"需要提升"。
    这些描述对下游没有价值，一律替换成和数据一致的表述。
    """
    if status == "已满足":
        return f"已达到岗位要求（{required_level}）"

    text = (text or "").strip()
    if text in ("无", "None", "none", "-", "暂无", "不适用"):
        text = ""  # 模型用"无"表示没什么可说的，按空处理
    fallback = (
        f"当前完全不具备这项能力；岗位要求达到「{required_level}」"
        if current_level == "无"
        else f"当前「{current_level}」，岗位要求「{required_level}」"
    )
    if not text:
        return fallback
    # 学生明明是"无"却写"已掌握"——矛盾
    if current_level == "无" and any(claim in text for claim in _ALREADY_CLAIMS):
        return fallback
    # 描述里提到的等级和岗位要求对不上（例如要求"中级"却写"提升到高级"）——也是矛盾
    mentioned = [level for level in _LEVEL_RANK if level != "无" and level in text]
    if mentioned and required_level not in mentioned:
        return fallback
    return text


def _format_skills(skills: list) -> str:
    if not skills:
        return "（无）"
    return "\n".join(f"- {s.get('skill')}（{s.get('level')}）" for s in skills)


def _format_requirements(requirements: list) -> str:
    if not requirements:
        return "（无）"
    return "\n".join(
        f"- {r.get('skill')}（重要度 {r.get('importance')}，要求 {r.get('level')}）"
        for r in requirements
    )


class GapItem(BaseModel):
    """模型对单项岗位要求的判断。

    注意这里**没有** current_level 字段：学生水平必须由代码从 Profile Agent
    的原始数据里查，不能由模型自己说了算。
    """

    skill: str = Field(description="照抄岗位要求的技能名称")
    required_level: Literal["入门", "初级", "中级", "高级"] = Field(description="照抄岗位要求的等级")
    supported_by: str = Field(description="支撑这项要求的学生技能名，没有就填'无'")
    gap: str = Field(description="一句话说明学生缺什么")

    @field_validator("required_level", mode="before")
    @classmethod
    def _normalize_required(cls, value):
        return normalize_level(value)


def _build_gap_schema(skill_names: list):
    """把 supported_by 收窄成「学生已有技能名 + 无」的枚举。

    枚举会写进 JSON schema 交给 Ollama 约束解码，模型没机会填出格的值。
    """
    options = tuple(dict.fromkeys(skill_names + ["无"]))  # 去重且保序
    item_model = create_model(
        "GapItem",
        __base__=GapItem,
        supported_by=(
            Literal[options],
            Field(description="只能从给定的学生技能名里选，或填'无'"),
        ),
    )
    return create_model("GapAnalysis", gaps=(list[item_model], Field(description="逐项比对结果")))


def judge_gaps(user_skills: list, job_requirements: list, analysis) -> list[dict]:
    """把模型回答整理成逐项的 skill_gaps —— **纯代码判定，不调模型、不做 IO**。

    单独抽出来的原因：阶段五"重新评估"要拿**同一批模型回答**，对更新前后的两套
    user_skills 各算一次缺口，用来对比能力提升的效果。判定逻辑与抽出来之前一字未改。

    参数
    ----
    user_skills : 学生能力表 [{skill, level, evidence}]，水平只从这里查
    job_requirements : 岗位要求，遍历以它为准，保证不漏项
    analysis : structured_invoke 的原始返回，只用到它的 ``gaps`` 列表
    """
    # 学生水平一律以 Profile Agent 的原数据为准
    student_level = {_norm_name(s["skill"]): s["level"] for s in user_skills}
    # 名字完全一致的，代码直接认定，不给模型出错的机会
    exact_match = {_norm_name(s["skill"]): s["skill"] for s in user_skills}
    requirement_names = {_norm_name(r["skill"]) for r in job_requirements}

    # 整理模型回答，同名只取第一条
    answers = {}
    invented = []
    for item in analysis.gaps:
        key = _norm_name(item.skill)
        if key not in requirement_names:
            invented.append(item.skill)  # 模型造了岗位要求里没有的技能，丢弃
        elif key not in answers:
            answers[key] = item

    # 用【岗位要求】来遍历而不是用模型的输出，保证一一对应：
    # 模型漏答的项也会出现在结果里，不会静默丢失
    gaps = []
    unanswered = []
    for req in job_requirements:
        key = _norm_name(req["skill"])
        item = answers.get(key)
        required_level = req["level"]
        importance = req["importance"]

        if key in exact_match:
            # 技能名和岗位要求完全一致，代码直接认定，不依赖模型判断
            supported_by = exact_match[key]
        elif item is not None:
            supported_by = item.supported_by.strip()
        else:
            # 模型漏答，按"未掌握"保守处理——宁可多报缺口，也不要漏报
            unanswered.append(req["skill"])
            supported_by = "无"

        # 指认的技能必须在学生技能表里存在，否则算"无"——防止凭空抬高学生水平
        current_level = student_level.get(_norm_name(supported_by), "无")
        if current_level == "无":
            supported_by = "无"

        status = _judge_status(current_level, required_level)

        if item is not None:
            gap_text = _clean_gap_text(item.gap, status, current_level, required_level)
        elif key in exact_match:
            gap_text = _clean_gap_text("", status, current_level, required_level)
        else:
            gap_text = f"模型未给出判断，按未掌握保守处理；岗位要求达到「{required_level}」"

        gaps.append(
            {
                "skill": req["skill"],
                "status": status,
                "supported_by": supported_by,
                "current_level": current_level,
                "required_level": required_level,
                "importance": importance,
                "priority": _judge_priority(status, importance),
                "gap": gap_text,
            }
        )

    if invented:
        print(f"[Assessment Agent] 警告：模型捏造了岗位要求里没有的技能，已丢弃 {invented}", flush=True)
    if unanswered:
        print(f"[Assessment Agent] 警告：模型漏答 {len(unanswered)} 项，已按未掌握补全 {unanswered}", flush=True)

    # 优先级降序 → 岗位重要度降序 → 技能名，保证结果稳定可复现
    priority_rank = {"高": 0, "中": 1, "低": 2}
    gaps.sort(key=lambda g: (priority_rank[g["priority"]], -g["importance"], g["skill"]))
    return gaps


def extract_answers(analysis) -> list[dict]:
    """把模型的**原始回答**转成可序列化的最小结构，只保留三个字段。

    为什么单独抽一个函数、而不塞进 ``judge_gaps``：``growth_agent`` 也在调用
    ``judge_gaps``，改它的签名或返回值会波及那边。这里只在 assessment 节点里
    顺手存一份原始回答，判定链路一行不动。

    口径（三条都重要）：

    1. **在清洗之前取** —— 拿到的是模型原话，不是 ``_clean_gap_text`` 回退后的文本；
    2. **只取 skill / supported_by / gap** —— 其余字段 ``judge_gaps`` 从不读取；
    3. **原样保存，不做任何改写** —— ``supported_by`` 缺失或为空就留 ``None``/``""``，
       **绝不在这里写成"无"**（"无"是 judge_gaps 的判定结果，不是模型的回答）。
    """
    answers: list[dict] = []
    for item in getattr(analysis, "gaps", None) or []:
        answers.append({
            "skill": _raw_field(item, "skill"),
            "supported_by": _raw_field(item, "supported_by"),
            "gap": _raw_field(item, "gap"),
        })
    return answers


def _raw_field(item, name):
    """按原值取字段：缺失或 None 保持 None，其余转成字符串，不做"补默认值"。"""
    value = getattr(item, name, None)
    return None if value is None else str(value)


def assessment_node(state: CareerState) -> dict:
    """LangGraph 节点：读取 user_skills + job_requirements，写入 skill_gaps。

    模型只负责"语义对应"（本节唯一的一次 LLM 调用），
    等级 / 状态 / 优先级全部交给 judge_gaps() 里的代码判定。
    """
    user_skills = state.get("user_skills") or []
    job_requirements = state.get("job_requirements") or []
    if not user_skills:
        raise ValueError("state 中缺少 user_skills，无法做能力差距分析")
    if not job_requirements:
        raise ValueError("state 中缺少 job_requirements，无法做能力差距分析")

    skill_names = [s["skill"] for s in user_skills]
    prompt = PROMPT.format(
        user_skills=_format_skills(user_skills),
        job_requirements=_format_requirements(job_requirements),
        skill_options="、".join(skill_names),
    )
    analysis = structured_invoke(prompt, _build_gap_schema(skill_names))

    # 先留一份模型的原始回答（清洗/过滤/回退之前），供阶段五做成长前后对比用；
    # 这份留档不参与任何判定，skill_gaps 的计算结果与以往完全一致。
    answers = extract_answers(analysis)

    gaps = judge_gaps(user_skills, job_requirements, analysis)

    log("Assessment Agent")
    return check_update(
        {"skill_gaps": gaps, "assessment_answers": answers}, "Assessment Agent"
    )
