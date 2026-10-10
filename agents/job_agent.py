"""Job Analysis Agent：把目标岗位拆解成结构化的技能要求。

证据驱动（阶段二）
------------------
除 ``target_job`` 外，本节点还读取 Retrieval Agent 写入的 ``job_evidence`` 与
``retrieval_status``，把真实检索证据作为**事实来源**注入提示词，并为每条岗位
要求标注来源：

- ``evidence_status``  supported / partially_supported / model_supplement
- ``evidence_refs``    实际支持该要求的证据编号（E01、E02… = job_evidence 的下标）
- ``source_companies`` 证据所属公司（来自证据记录，不来自模型文本）
- ``importance_basis`` profile_skill_importance / model_generated
- ``level_basis``      jd_text / profile_level / model_inferred

分工原则（与 Assessment Agent 一致：模型做语义，代码做判定）
------------------------------------------------------------
- **模型**负责文字生成与语义对应，并可在给定编号范围内提出证据引用；
- **程序**负责一切可判定的结论：编号回查、公司/原文/重要程度的取值、
  等级来源判定、多家公司等级冲突取最严。

三条硬约束
----------
1. 模型提出的编号必须在**本轮 job_evidence** 里能回查到，否则丢弃并告警；
2. 公司、原文、重要程度**只从回查到的证据记录里取**，不采信模型填写的文本；
3. 技能名只是"包含"某个规范名（如"Agent 与工作流编排"含 "Agent"）**不算**直接
   证据 —— 只有归一化后完全同名才算 ``supported``，别名/语义关联一律
   ``partially_supported``。规范名由规则层从 ``SkillVocabulary`` 解析，不问模型。

降级
----
没有索引、没有匹配证据或检索报错时，``job_evidence`` 为空 —— 岗位要求照常生成，
但每条都标记为 ``model_supplement`` + ``importance_basis = "model_generated"``，
系统本身可判定"这条没有 JD 依据"，不再只靠终端提示。
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from agents.llm import structured_invoke
from agents.retriever import SkillVocabulary
from agents.utils import (
    SKILL_LEVELS,
    check_non_empty,
    dedupe_by,
    log,
    normalize_level,
    resolve_canonical,
)
from graph.state import CareerState, check_update

# 证据编号：E01 = job_evidence[0]
_REF_PATTERN = re.compile(r"^E\d{2,}$")
_NO_REF_TOKENS = ("", "无", "none", "n/a", "-")

# 与 check_non_empty 的下限保持一致：技能名清理后若不足 3 条，宁可保留原始输出也不让节点崩
MIN_REQUIREMENTS = 3

# 提示词里的「岗位能力分类」清单。它们是**检查覆盖面的标签，不是技能名**，
# 小模型很容易原样抄进 skill 字段（如"Agent 与工作流编排""工程化与部署"），
# 于是既查不到知识库、又和真实技能名重复。
CATEGORY_LABELS = (
    "编程语言",
    "大模型调用与提示词工程",
    "Agent 与工作流编排",
    "RAG 检索增强",
    "后端服务",
    "工程化与部署",
)
CATEGORY_LABEL_SET = frozenset(
    str(label).strip().lower().replace(" ", "") for label in CATEGORY_LABELS
)

# JD 原文里的等级措辞 → 四档。**由强到弱排列，取第一个命中**，
# 这样"熟练掌握"会命中"熟练"(高级)，而不是先命中"掌握"(中级)。
_JD_LEVEL_WORDS = (
    ("精通", "高级"),
    ("熟练", "高级"),
    ("掌握", "中级"),
    ("熟悉", "中级"),
    ("会用", "初级"),
    ("了解", "入门"),
    ("听说", "入门"),
)

PROMPT = """你是一名资深技术招聘专家。请分析「{job}」这个岗位，
拆解出这个岗位真正要求的核心技能。

【岗位知识库检索证据】
{evidence_block}

【岗位定位】先分清这个岗位属于哪一类，再据此拆解：
- 如果是"大模型 / AI 应用开发"类岗位：它是把大模型能力落地成产品的**工程岗**，
  不是训练模型的算法岗。此时下列**能力分类**每一类都要至少覆盖一项，缺一不可：
  ① 编程语言            → 具体技能如 Python
  ② 大模型调用与提示词工程 → 具体技能如 LLM API、Prompt Engineering
  ③ Agent 与工作流编排    → 具体技能如 Agent、LangChain、LangGraph、Function Calling
                           （RAG 不能算作这一项，必须单独出现）
  ④ RAG 检索增强         → 具体技能如 RAG、Embedding
  ⑤ 后端服务            → 具体技能如 后端 API 开发、FastAPI
  ⑥ 工程化与部署         → 具体技能如 Docker、Git、Linux
  在此基础上再补充该岗位会考察的其他技能，不要用 PyTorch、深度学习理论顶替上面这些。
- 如果是算法 / 研究类岗位：才以机器学习、深度学习框架、数学基础为核心。

【要求】
1. 给出 6~10 项核心技能，覆盖编程语言、框架、工程能力、计算机基础等不同层面。
2. **skill 要写"具体技能名"，不要写上面的分类名。**
   ① ~ ⑥ 是帮你检查覆盖面的**分类标签**，不是技能名：
   写"Agent"而不是"Agent 与工作流编排"，写"后端 API 开发"而不是"后端服务"，
   写"Docker"或"Git"而不是"工程化与部署"，写"LLM API"而不是"大模型调用与提示词工程"。
   只有当某个分类名本身就是规范技能名（如 RAG）时才能直接用。
3. 只列这个岗位真正会考察的技能，不要凑数。优先采用上面证据里出现过的技能。
4. **同一个技能只写一次。** 不要用分类标签和具体技能名重复列同一件事
   （例如"大模型调用与提示词工程"和"Prompt Engineering"是同一条，只保留后者）。
5. importance 是 1~5 的整数，5 表示最重要。必须有区分度，
   不要把每项都写成 5，最多 2 项可以是 5。
6. level 是该岗位对这项技能的推荐能力等级（入门/初级/中级/高级）。
7. reason 用一句话说明这项技能在岗位里具体用来做什么。
8. evidence_refs 只能填上面【岗位知识库检索证据】里出现过的编号（如 E01、E02），
   可以填多个；名称和证据里的技能不一样、但语义相关的也可以引用。
   确实找不到能支撑该项的证据时，填 ["无"]。
   **不得编造编号、公司名或原文**；上面没有证据时，所有项都填 ["无"]。
9. 全部用中文，技能名称保留英文原文（如 Python、FastAPI、Docker）。"""


class JobRequirement(BaseModel):
    """岗位对单项技能的要求。"""

    skill: str = Field(description="技能名称")
    importance: int = Field(description="重要程度，1~5 的整数，5 最重要")
    level: Literal["入门", "初级", "中级", "高级"] = Field(description="岗位要求的推荐能力等级")
    reason: str = Field(description="这项技能在岗位中的用途")
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="支撑该项要求的证据编号，如 ['E01','E03']；没有就填 ['无']",
    )

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_level(cls, value):
        return normalize_level(value)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _coerce_refs(cls, value):
        """容忍小模型把列表写成字符串或 null。真正的合法性在程序侧回查。"""
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [] if text.lower() in _NO_REF_TOKENS else [text]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


class JobAnalysis(BaseModel):
    """Job Agent 的结构化输出。"""

    requirements: list[JobRequirement] = Field(description="岗位核心技能要求列表")


# ── 技能词表（惰性，读不到就降级为"不做名称归一"）──────────────────────
_vocabulary: SkillVocabulary | None = None
_vocabulary_unavailable = False


def get_vocabulary() -> SkillVocabulary | None:
    """取技能词表。不可用时返回 None，本节点降级为"只靠模型引用"，不中断流程。"""
    global _vocabulary, _vocabulary_unavailable
    if _vocabulary is None and not _vocabulary_unavailable:
        try:
            _vocabulary = SkillVocabulary()
        except Exception as exc:  # 画像文件缺失 / 损坏
            _vocabulary_unavailable = True
            print(
                f"[Job Agent] 警告：技能词表不可用，跳过技能名归一（{type(exc).__name__}: {exc}）",
                flush=True,
            )
    return _vocabulary


# ── 纯函数工具 ──────────────────────────────────────────────────────────
def _normalize_skill_name(name) -> str:
    return str(name or "").strip().lower().replace(" ", "")


def evidence_ref(index: int) -> str:
    """job_evidence 下标 → 证据编号。"""
    return f"E{index + 1:02d}"


def _jd_level_from_note(note) -> tuple[str, str] | None:
    """从 JD 原文里抽出**明确写出**的等级措辞，返回 (措辞, 等级)；没写就返回 None。

    绝不能回退到 ``normalize_level`` 的默认值（初级）—— 那会把"JD 没写等级"
    伪装成"JD 写了初级"。技能有证据不等于技能等级有证据。
    """
    text = str(note or "")
    for word, level in _JD_LEVEL_WORDS:
        if word in text:
            return word, level
    return None


def _strictest(levels) -> str | None:
    """取最严格的等级（入门 < 初级 < 中级 < 高级）；没有合法值返回 None。"""
    known = [lv for lv in levels if lv in SKILL_LEVELS]
    if not known:
        return None
    return max(known, key=SKILL_LEVELS.index)


def _resolve_canonical(skill_name) -> str | None:
    """把要求名归一到知识库的规范技能名；仅唯一命中时采用。

    唯一性很关键：名字里恰好包含多个技能名时不猜，交给模型引用。
    """
    return resolve_canonical(skill_name, get_vocabulary())


def is_category_label(skill_name) -> bool:
    """判断这个名字是不是提示词里的"岗位能力分类标签"而非具体技能名。"""
    return _normalize_skill_name(skill_name) in CATEGORY_LABEL_SET


def drop_category_labels(requirements: list, dropped: list) -> list:
    """剔除**无法归一**的分类标签。

    分类标签不是技能名：能唯一归一到规范技能的（如"后端服务"→"后端 API 开发"）
    留下，由后面的规范名去重合并；归不了的（如"工程化与部署"，规范技能表里
    没有对应项）说明这句话没有落到任何具体技能上，丢弃并记录，避免它在下游被
    当成一个凭空存在的"技能"。

    另外两道保护：
    - 只对**已经有至少 3 条**的输出生效，清理后不足 3 条就整条回退（见 job_node）；
    - 分类标签之外的技能名一律不动。
    """
    kept = []
    for req in requirements:
        name = req.get("skill")
        if is_category_label(name) and _resolve_canonical(name) is None:
            dropped.append(str(name).strip())
            continue
        kept.append(req)
    return kept


def dedupe_by_canonical(requirements: list, merged: list) -> list:
    """按**规范技能名**去重，消除"分类标签 + 具体技能名"的重复项。

    例如模型同时给出"大模型调用与提示词工程"和"Prompt Engineering"，二者归一后
    是同一个技能，只保留一条 —— 否则下游会把同一个缺口当成两个，出现
    "Prompt Engineering 明显不足"与"大模型调用与提示词工程 已满足"并存的矛盾。

    同名组里**优先保留技能名本身就是规范名的那条**，下游拿到的才是干净名字。
    无法归一的技能按原始名各成一组，不做任何合并。
    """
    groups: dict[str, list] = {}
    order: list[str] = []
    for req in requirements:
        canonical = _resolve_canonical(req.get("skill"))
        key = canonical or f"__raw__{_normalize_skill_name(req.get('skill'))}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(req)

    result = []
    for key in order:
        items = groups[key]
        if len(items) > 1:
            merged.append(items[0].get("skill"))
        canonical = _resolve_canonical(items[0].get("skill"))
        if canonical:
            exact = [
                item
                for item in items
                if _normalize_skill_name(item.get("skill")) == _normalize_skill_name(canonical)
            ]
            result.append((exact or items)[0])
        else:
            result.append(items[0])
    return result


def format_evidence_block(evidence: list, retrieval_status: str | None) -> str:
    """把检索证据整理成提示词里的一段。编号由程序给出，模型只能引用这些编号。"""
    if not evidence:
        return (
            f"（本轮岗位知识库检索状态：{retrieval_status or '未提供'}，没有可用证据。"
            "所有 evidence_refs 一律填 [\"无\"]，岗位要求按你自己的判断拆解。）"
        )
    lines = []
    for index, item in enumerate(evidence):
        lines.append(
            f"{evidence_ref(index)}｜公司：{item.get('company_slug') or '未标注'}"
            f"｜技能：{item.get('skill')}"
            f"｜要求性质：{item.get('requirement_type')}"
            f"｜章节：{item.get('context')}"
            f"｜原文：{item.get('note')}"
        )
    return "\n".join(lines)


def _attach_evidence(requirement: dict, evidence: list, rejected: list) -> dict:
    """给一条岗位要求回填来源信息。所有结论由程序算，不采信模型填写的文本。"""
    by_ref = {evidence_ref(i): i for i in range(len(evidence))}

    # 1) 校验模型提出的编号：必须是本轮真实存在的证据编号
    model_indexes: list[int] = []
    for raw in requirement.get("evidence_refs") or []:
        token = str(raw or "").strip()
        if token.lower() in _NO_REF_TOKENS:
            continue
        if not _REF_PATTERN.match(token) or token not in by_ref:
            rejected.append(token)
            continue
        position = by_ref[token]
        if position not in model_indexes:
            model_indexes.append(position)

    # 2) 规则层：技能名归一后按规范名直接取证据，不问模型
    canonical = _resolve_canonical(requirement.get("skill"))
    rule_indexes = (
        [i for i, item in enumerate(evidence) if item.get("skill") == canonical]
        if canonical
        else []
    )

    # 规则层能定就完全用规则层的（模型那几条是冗余的）；否则才用模型引用
    if rule_indexes:
        indexes = rule_indexes
        exact_name = _normalize_skill_name(requirement.get("skill")) == _normalize_skill_name(canonical)
        status = "supported" if exact_name else "partially_supported"
    elif model_indexes:
        indexes = model_indexes
        status = "partially_supported"
    else:
        indexes = []
        status = "model_supplement"

    if not indexes:
        return {
            **requirement,
            "evidence_status": "model_supplement",
            "evidence_refs": [],
            "source_companies": [],
            "importance_basis": "model_generated",
            "level_basis": {"origin": "model_inferred", "quote": None, "by_company": {}},
        }

    picked = [evidence[i] for i in indexes]

    # 3) 等级依据：JD 原文措辞优先 → 画像推荐等级 → 模型推断
    by_company: dict[str, dict] = {}
    for item in picked:
        found = _jd_level_from_note(item.get("note"))
        if not found:
            continue
        word, level = found
        company = item.get("company_slug") or "未标注公司"
        previous = by_company.get(company)
        if previous is None or SKILL_LEVELS.index(level) > SKILL_LEVELS.index(previous["level"]):
            by_company[company] = {"level": level, "quote": word}

    if by_company:
        level = _strictest([entry["level"] for entry in by_company.values()])
        quote = next(entry["quote"] for entry in by_company.values() if entry["level"] == level)
        level_basis = {"origin": "jd_text", "quote": quote, "by_company": by_company}
    else:
        profile_level = _strictest([item.get("level") for item in picked])
        if profile_level:
            level = profile_level
            level_basis = {"origin": "profile_level", "quote": None, "by_company": {}}
        else:
            level = requirement.get("level")
            level_basis = {"origin": "model_inferred", "quote": None, "by_company": {}}

    # 4) 重要程度：沿用画像的技能级数据；没有才用模型值并标记
    profile_importance = [
        item["importance"] for item in picked if isinstance(item.get("importance"), int)
    ]
    if profile_importance:
        importance = max(1, min(5, max(profile_importance)))
        importance_basis = "profile_skill_importance"
    else:
        importance = requirement.get("importance")
        importance_basis = "model_generated"

    return {
        **requirement,
        "importance": importance,
        "level": level,
        "evidence_status": status,
        "evidence_refs": [evidence_ref(i) for i in indexes],
        "source_companies": sorted(
            {item.get("company_slug") for item in picked if item.get("company_slug")}
        ),
        "importance_basis": importance_basis,
        "level_basis": level_basis,
    }


def job_node(state: CareerState) -> dict:
    """LangGraph 节点：读取 target_job + job_evidence，写入 job_requirements。

    输出字段与既有结构兼容：``skill`` / ``importance`` / ``level`` / ``reason``
    语义不变，其余为本次新增的来源标注。
    """
    target_job = (state.get("target_job") or "").strip()
    if not target_job:
        raise ValueError("state 中缺少 target_job，无法分析岗位要求")

    evidence = list(state.get("job_evidence") or [])
    retrieval_status = state.get("retrieval_status")

    prompt = PROMPT.format(
        job=target_job,
        evidence_block=format_evidence_block(evidence, retrieval_status),
    )
    analysis = structured_invoke(prompt, JobAnalysis)

    requirements = []
    for req in analysis.requirements:
        item = req.model_dump()
        # 小模型偶尔会给出越界的 importance，这里兜一下底
        item["importance"] = max(1, min(5, item["importance"]))
        requirements.append(item)

    # 模型经常把同一个技能列两遍（如 Git），先按原样名字去重
    requirements = dedupe_by(requirements, key="skill")

    # 再把"岗位能力分类标签"和"同一个技能的不同说法"清掉。
    # 两步都可能减少条数，所以先试算，清理后仍够 3 条才采用，否则整条回退 ——
    # 宁可让一条标签漏过去，也不要因此把节点搞崩。
    dropped_labels: list[str] = []
    merged_dupes: list[str] = []
    cleaned = dedupe_by_canonical(drop_category_labels(requirements, dropped_labels), merged_dupes)
    if len(cleaned) >= MIN_REQUIREMENTS:
        requirements = cleaned
        if dropped_labels:
            print(
                f"[Job Agent] 警告：模型把岗位能力分类当成了技能名，已丢弃无法对应具体技能的"
                f"{sorted(set(dropped_labels))}",
                flush=True,
            )
        if merged_dupes:
            print(
                f"[Job Agent] 警告：以下技能名归一后重复，已合并为规范技能名：{sorted(set(merged_dupes))}",
                flush=True,
            )
    else:
        print(
            f"[Job Agent] 警告：技能名清理后只剩 {len(cleaned)} 条，低于下限 {MIN_REQUIREMENTS}，"
            f"已保留模型原始输出（未丢弃分类标签）",
            flush=True,
        )

    check_non_empty(requirements, "Job Agent 的岗位技能列表", minimum=MIN_REQUIREMENTS)

    # 回填证据来源（会覆盖 importance / level，所以必须排在排序之前）
    rejected: list[str] = []
    requirements = [_attach_evidence(req, evidence, rejected) for req in requirements]
    if rejected:
        print(
            f"[Job Agent] 警告：模型提出了本轮不存在的证据编号，已丢弃 {sorted(set(rejected))}",
            flush=True,
        )

    # 按重要程度降序，方便后续 Agent 优先处理关键缺口
    requirements.sort(key=lambda r: r["importance"], reverse=True)

    log("Job Agent")
    return check_update({"job_requirements": requirements}, "Job Agent")
