"""Learning Planning Agent：根据 skill_gaps 制定学习路线。

阶段三补强（对应端到端验收报告 S1 / S2 / S5 / S8）
----------------------------------------------------
原则不变：**模型负责写文字，可判定的结论一律由代码算**。

1. **技能名归一（S1）**：模型很容易把岗位"能力分类标签"（如"Agent 与工作流编排"）
   当成技能名。直接拿这种名字查 Skill 知识库会全部落空，学习标准就只好靠模型编。
   查询前先经 ``SkillVocabulary`` 归一，**只有唯一命中才采用**；没命中或有歧义
   一律记入 ``unmapped_covers`` 并告警，绝不猜测。
2. **covers 规范化与降级剔除（S2）**：``covers`` 只保留规范技能名；已满足 /
   低优先级的缺口不得占据学习阶段，会被移出并记入 ``dropped_low_priority``。
3. **覆盖率与等级一致性（S2 / S8）**：高、中优先级缺口若没有任何阶段覆盖，
   或阶段的 goal 与 completion_criteria 目标等级自相矛盾，都会产出明确告警，
   而不是静默通过。
4. **总时长上限（S8）**：超过 ``MAX_TOTAL_WEEKS`` 时报告超出量，
   **不会通过删掉重要缺口来凑上限**。
5. **不伪造知识库标准（S5）**：无法归一（因而查不到能力标准）的缺口会被显式
   列进 prompt，并明确告知模型"这些不是知识库来源，不得伪造成知识库标准"。

不修改 ``skill_gaps`` 的结构，也不改动 ``learning_plan`` 的既有字段。
每个阶段新增三个可追踪字段：``skill_mapping`` / ``unmapped_covers`` /
``dropped_low_priority``（后者为空时不写）。
"""

import re

from pydantic import BaseModel, Field

from agents.llm import structured_invoke
from agents.retriever import SkillVocabulary
from agents.skill_knowledge import SkillKnowledgeBase
from agents.utils import (
    SKILL_LEVELS,
    build_skill_mapping,
    check_non_empty,
    dedupe_by,
    log,
    resolve_canonical,
)
from graph.state import CareerState, check_update

# 学习路线总时长上限（约一年）。超过只报告，不删缺口。
MAX_TOTAL_WEEKS = 52

# 认定为"低优先级"的优先级取值；已满足的缺口优先级同样是"低"。
LOW_PRIORITY = "低"

# 防漏回路最多补几轮。补齐的 covers 都是规范名且缺口是高优先级，一轮必然收敛，
# 留第二轮只为防御 repair 把补齐项又剔掉之类的意外，且不会无限循环。
BACKFILL_ROUNDS = 2

# 知识库没给预计周数时，补出来的阶段默认周数
DEFAULT_BACKFILL_WEEKS = 4

# 学习路线最少保留几个阶段，与 learning_node 里 check_non_empty(minimum=2) 的口径一致。
# 删除空阶段时用它兜底：删到这个下限就不再删。
MIN_STAGES = 2

# 等级措辞对齐的字段。topic 也纳入 —— 否则会出现 topic「高级技能学习」
# 而 goal「掌握中级技能」这种同一阶段自相矛盾的写法。
LEVEL_ALIGN_FIELDS = ("topic", "goal", "completion_criteria")

# 完成标准与知识库标准做包含匹配时的最短长度，避免短句误命中
_MIN_GUIDE_MATCH_LEN = 8

PROMPT = """你是一名技术学习路径规划师。请为一名想成为「{target_job}」的大学生
安排一条学习路线。

【他的能力差距（已按优先级排序）】
{gaps}

【他目前已有的技能】
{user_skills}

【岗位知识库·技能能力标准（检索自 Skill 知识库，供你参考各等级该达到什么程度）】
{skill_knowledge}

【没有知识库依据的缺口】
{unmapped_skills}
以上缺口的**能力标准不在知识库收录范围内**。可以按通用工程常识安排，
但不得把你自己编的标准说成"知识库要求"，也不得为它们虚构等级标准。

【要求】
1. 只针对上面**优先级为"高"或"中"**的缺口安排学习，不要给"低"或"已满足"的
   缺口排期——它们已经达标，再排一次是浪费时间。
2. 一共安排 3~5 个阶段。**不要贪多**，不要把所有技术都塞进来，
   宁可少而深。同一个阶段内可以合并相关性强的技能。
3. 严格按学习的前置关系排序：必须先学的基础排在前面，
   （例如先有 Python 基础再学后端框架，先会后端再学部署）。
4. 上面每个缺口都标了编号和优先级。**优先级"高"的缺口必须一条不漏地全部
   出现在某个阶段的 covers 里**（清单开头写了有几条"高"，照这个数字清点），
   而且要排在更靠前的阶段，不能被低优先级技能挤到后面。
   如果你自己的 3~5 个阶段装不下，就合并相关技能，而不是丢掉高优先级缺口。
5. 每个阶段要说清楚：
   - goal：为什么要学这个、它解决哪个能力缺口；
   - covers：这一阶段覆盖了上面哪几项差距。
     **只写技能名本身**，必须和上面给出的技能名一字不差，
     不要加括号、等级或任何修饰（写"LLM API"，不要写"LLM API（高级）"）；
   - prerequisite：学之前需要具备什么（参考他已有的技能）；
   - completion_criteria：达到什么程度算学会，要可验证，
     例如"能独立开发一个提供 3 个接口的 AI 服务并写清 README"，
     不要写"掌握 FastAPI"这种没法验收的话；
     **这里提到的能力等级必须和 goal 里说的是同一个等级**，
     不要 goal 说"高级特性"、完成标准却只写中级要求；
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
    """把缺口清单按编号 + 优先级列出来，并点明高优先级缺口的条数。

    显式编号比无编号的短横线列表更容易让 3B 模型"数着写"，减少漏项。
    """
    if not gaps:
        return "（无）"
    high = sum(1 for g in gaps if g.get("priority") == "高")
    lines = [
        f"共 {len(gaps)} 项缺口，其中优先级「高」{high} 项 —— "
        f"这 {high} 项必须**一项不漏**地出现在下面的路线里。"
    ]
    lines.extend(
        f"{index}. [{g.get('priority')}] {g.get('skill')}｜岗位重要度 {g.get('importance')}｜"
        f"当前 {g.get('current_level')}，要求 {g.get('required_level')}｜{g.get('gap')}"
        for index, g in enumerate(gaps, start=1)
    )
    return "\n".join(lines)


def _format_skills(skills: list) -> str:
    if not skills:
        return "（无）"
    return "、".join(f"{s.get('skill')}（{s.get('level')}）" for s in skills)


# ── 知识库 / 词表加载（都允许失败，失败则降级）────────────────────────────
def _load_vocabulary() -> SkillVocabulary | None:
    """取技能词表。不可用时返回 None，调用方降级为"不做技能名归一"。"""
    try:
        return SkillVocabulary()
    except Exception as exc:  # noqa: BLE001 - 降级路径
        log("Learning Agent", f"技能词表不可用，跳过技能名归一：{exc}")
        return None


def _load_skill_base() -> SkillKnowledgeBase | None:
    """取 Skill 知识库。不可用时返回 None，调用方降级为纯模型生成。

    每次都重新构造、不缓存：既让测试可以直接替换 `SkillKnowledgeBase`，
    也让知识库文件的改动立刻生效。
    """
    try:
        return SkillKnowledgeBase()
    except Exception as exc:  # noqa: BLE001 - 降级路径
        log("Learning Agent", f"Skill 知识库加载失败，回退纯模型生成：{exc}")
        return None


def _skill_knowledge_block(names: list[str], base: SkillKnowledgeBase | None) -> str:
    """把规范技能名的能力标准拼成 prompt 段落；知识库不可用时给降级提示。"""
    if base is None:
        return "（知识库暂时不可用，请按通用方法安排学习）"
    if not names:
        return "（无差距技能可检索）"
    blocks = base.format_for_prompt(names)
    return blocks or "（差距技能均不在知识库收录范围，按通用知识安排即可）"


# ── 纯函数：技能名归一与阶段修正（S1 / S2）────────────────────────────────
def normalize_covers(covers, vocabulary) -> tuple[list[str], dict, list[str]]:
    """把一批 covers 归一成规范技能名。

    返回 `(canonical, mapping, unmapped)`：

    - ``canonical``：去重后的规范技能名，**只保留能唯一归一的**；
    - ``mapping``：``{模型写的原名: 规范技能名}``，供下游追踪；
    - ``unmapped``：没命中或有歧义的原名，直接列出，不猜测、不替换。
    """
    canonical: list[str] = []
    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    for raw in covers or []:
        name = str(raw or "").strip()
        if not name or name in mapping or name in unmapped:
            continue
        resolved = resolve_canonical(name, vocabulary)
        if resolved is None:
            unmapped.append(name)
            continue
        mapping[name] = resolved
        if resolved not in canonical:
            canonical.append(resolved)
    return canonical, mapping, unmapped


def _gap_lookup(gaps: list, vocabulary) -> dict:
    """``{规范技能名: gap}`` —— 同一规范名只取第一条，避免一个缺口覆盖另一个。"""
    lookup: dict[str, dict] = {}
    for gap in gaps or []:
        canonical = resolve_canonical(gap.get("skill"), vocabulary)
        if canonical and canonical not in lookup:
            lookup[canonical] = gap
    return lookup


def repair_stages(stages: list, gaps: list, vocabulary) -> list[str]:
    """**原地**修正每个阶段的 covers，返回问题清单。

    - ``covers`` 只保留 Skill 知识库的规范技能名，无法唯一归一的移入
      ``unmapped_covers``；
    - 已满足 / 低优先级缺口不得占据 covers，移入 ``dropped_low_priority``；
    - 每阶段的 ``skill_mapping`` 保留"原始名 → 规范名"，便于下游追踪。

    修正只动 covers 与这几个追踪字段，不重写模型写的 goal / 完成标准。
    """
    issues: list[str] = []
    lookup = _gap_lookup(gaps, vocabulary)

    for index, stage in enumerate(stages, start=1):
        canonical, mapping, unmapped = normalize_covers(stage.get("covers"), vocabulary)
        kept: list[str] = []
        dropped: list[str] = []
        unknown: list[str] = []
        for name in canonical:
            gap = lookup.get(name)
            if gap is None:
                unknown.append(name)
                kept.append(name)
            elif gap.get("priority") == LOW_PRIORITY:
                dropped.append(name)
            else:
                kept.append(name)

        # 幂等合并：repair_stages 会被调用两次（节点内一次、validate 里再一次），
        # 第二次面对的是**已经归一过**的 covers，直接覆盖会把首次记下的原始映射
        # 与剔除结果抹掉。所以追踪字段只累加、不清空。
        # 另外只记"确实改过名字"的项：原名与规范名相同的恒等映射没有追踪价值，
        # 记下来反而会让第二次调用混进一堆 "Agent": "Agent" 之类的噪声。
        renames = {
            raw: canonical
            for raw, canonical in mapping.items()
            if str(raw).strip() != str(canonical).strip()
        }
        stage["covers"] = kept
        stage["skill_mapping"] = {**(stage.get("skill_mapping") or {}), **renames}
        stage["unmapped_covers"] = list(
            dict.fromkeys([*(stage.get("unmapped_covers") or []), *unmapped])
        )
        if dropped:
            stage["dropped_low_priority"] = list(
                dict.fromkeys([*(stage.get("dropped_low_priority") or []), *dropped])
            )

        if unmapped:
            issues.append(
                f"阶段 {index} 的 covers 有 {len(unmapped)} 项无法归一为规范技能名：{unmapped}"
                f"（未猜测，已移出 covers）"
            )
        if dropped:
            issues.append(
                f"阶段 {index} 的 covers 含已满足/低优先级技能：{dropped}（已移出 covers）"
            )
        if unknown:
            issues.append(f"阶段 {index} 的 covers 含 skill_gaps 之外的技能：{unknown}")
        if not kept:
            issues.append(f"阶段 {index} 修正后 covers 为空，未覆盖任何高/中优先级缺口")
    return issues


def covered_skills(stages: list) -> set[str]:
    """所有阶段 covers 的并集（都是规范技能名）。"""
    covered: set[str] = set()
    for stage in stages:
        covered.update(stage.get("covers") or [])
    return covered


def check_coverage(stages: list, gaps: list, vocabulary) -> list[str]:
    """高、中优先级缺口是否被覆盖。未被覆盖的**必须显式报告**，不能静默放行。"""
    covered = covered_skills(stages)

    issues: list[str] = []
    for gap in gaps or []:
        if gap.get("priority") == LOW_PRIORITY:
            continue
        name = gap.get("skill")
        canonical = resolve_canonical(name, vocabulary)
        if canonical is None:
            issues.append(
                f"缺口「{name}」（优先级 {gap.get('priority')}）无法归一为规范技能名，"
                f"无法核对是否被覆盖"
            )
            continue
        if canonical not in covered:
            issues.append(
                f"缺口「{name}」（优先级 {gap.get('priority')}、岗位重要度 "
                f"{gap.get('importance')}）没有被任何学习阶段覆盖"
            )
    return issues


# ── 防漏回路：代码自动补齐未被覆盖的高优先级缺口（问题 1）────────────────
def uncovered_high_gaps(stages: list, gaps: list, vocabulary) -> list[dict]:
    """找出**没有任何阶段覆盖**的高优先级缺口，按岗位重要度降序。

    只返回能唯一归一为规范技能名的缺口：归一不了的连"该覆盖哪个技能"都定不下来，
    补一个阶段也只是编内容，所以交给 check_coverage 去报告，不在这里硬凑。
    """
    covered = covered_skills(stages)
    seen: set[str] = set()
    result: list[dict] = []
    for gap in gaps or []:
        if gap.get("priority") == LOW_PRIORITY:
            continue
        canonical = resolve_canonical(gap.get("skill"), vocabulary)
        if canonical is None or canonical in covered or canonical in seen:
            continue
        seen.add(canonical)
        result.append({"canonical": canonical, "gap": gap})
    result.sort(key=lambda item: -(item["gap"].get("importance") or 0))
    return result


def build_backfill_stage(canonical: str, gap: dict, base, stage_number: int) -> dict:
    """用知识库里的等级标准**由代码生成**一个补漏阶段，不调用模型。

    completion_criteria 直接复用该技能在目标等级上的知识库标准原文，
    这样补出来的内容是"知识库说法"而不是模型或程序编的话；知识库没有这条技能时
    退化成一句不承诺具体等级的通用描述。
    """
    required = gap.get("required_level")
    required = required if required in SKILL_LEVELS else "中级"

    entry = base.get(canonical) if base is not None else None
    entry = entry or {}
    guides = entry.get("level_guides") or {}
    criteria = str(guides.get(required, "")).strip()
    if not criteria:
        criteria = (
            f"能独立完成与「{canonical}」相关的岗位任务，达到岗位要求的「{required}」水平"
        )

    prereqs = [str(p).strip() for p in entry.get("prerequisites") or [] if str(p).strip()]
    weeks = entry.get("estimated_weeks")
    if not isinstance(weeks, int) or weeks <= 0:
        weeks = DEFAULT_BACKFILL_WEEKS

    return {
        "stage": stage_number,
        "topic": canonical,
        "goal": f"补齐岗位高优先级缺口「{canonical}」，达到岗位要求的「{required}」水平",
        "covers": [canonical],
        "prerequisite": "、".join(prereqs) if prereqs else "无特殊前置",
        "completion_criteria": criteria,
        "estimated_weeks": weeks,
        # 追踪标记：这个阶段是程序补出来的，不是模型写的
        "backfilled": True,
    }


def backfill_uncovered_gaps(stages: list, gaps: list, vocabulary, base,
                            max_rounds: int = BACKFILL_ROUNDS) -> list[str]:
    """防漏回路：把漏掉的高优先级缺口用代码补成阶段，返回处理说明。

    这是"代码自动补齐"而不是"再求模型自觉"——模型漏了就由程序补上，
    补完再校验，最多 ``max_rounds`` 轮，避免死循环。

    补出来的阶段统一**追加在末尾并重新编号**：插入到中间需要判断前置关系，
    规则一旦写歪反而会打乱模型已经排好的学习顺序，追加不会破坏既有顺序。
    """
    notes: list[str] = []
    for _ in range(max(0, max_rounds)):
        missing = uncovered_high_gaps(stages, gaps, vocabulary)
        if not missing:
            break
        for item in missing:
            stages.append(
                build_backfill_stage(item["canonical"], item["gap"], base, len(stages) + 1)
            )
        notes.append(
            f"已用代码自动补齐 {len(missing)} 个未被覆盖的高优先级缺口："
            f"{[item['canonical'] for item in missing]}（不是靠模型自觉）"
        )

    for index, stage in enumerate(stages, start=1):
        stage["stage"] = index
    return notes


# ── 等级措辞对齐（问题 3）────────────────────────────────────────────────
def _stage_target_level(stage: dict, lookup: dict) -> str | None:
    """阶段的目标等级 = 所覆盖缺口里最严格的那个岗位要求等级。"""
    target: str | None = None
    for name in stage.get("covers") or []:
        gap = lookup.get(name)
        if gap is None:
            continue
        required = gap.get("required_level")
        if required in SKILL_LEVELS and (
            target is None or SKILL_LEVELS.index(required) > SKILL_LEVELS.index(target)
        ):
            target = required
    return target


def realign_level_words(text, target: str) -> str:
    """把文字里与目标等级不同的等级词替换成目标等级。

    只替换**等级词本身**（入门/初级/中级/高级），其余文字一个字不动。
    小模型爱写"掌握 Python 的高级特性"，但该技能岗位只要求中级 —— 这类措辞
    会让下游误以为要学到高级，所以在进入结果之前由代码统一拉齐。
    """
    fixed = str(text or "")
    for level in SKILL_LEVELS:
        if level != target and level in fixed:
            fixed = fixed.replace(level, target)
    return fixed


def align_stage_levels(stages: list, gaps: list, vocabulary, base=None) -> list[str]:
    """把各阶段的 topic / goal / completion_criteria 等级措辞对齐到缺口要求等级。

    与 :func:`check_level_consistency` 是两个东西：那个只**判断并报告**，
    这个负责**改**。改完仍然要过一遍校验，报不报警由校验说了算。
    找不到目标等级（阶段没覆盖任何带 required_level 的缺口）时不动文字。

    三个字段一起对齐是必须的：只改 goal 会把矛盾从"goal 与岗位要求不符"
    变成"topic 与 goal 不符"（例如 topic 仍写「高级技能学习」、goal 已改「中级」）。
    判定冲突仍复用同一个 :func:`realign_level_words`，没有引入新的替换规则。
    """
    lookup = _gap_lookup(gaps, vocabulary)
    notes: list[str] = []
    for index, stage in enumerate(stages, start=1):
        target = _stage_target_level(stage, lookup)
        if target is None:
            continue
        for field in LEVEL_ALIGN_FIELDS:
            before = str(stage.get(field) or "")
            after = realign_level_words(before, target)
            if after != before:  # 不含等级词的字段原样返回，不会产生无谓改动
                stage[field] = after
                notes.append(f"阶段 {index} 的 {field} 等级措辞已对齐为「{target}」")
    return notes


def droppable_empty_stage(stage: dict) -> str | None:
    """covers 为空的阶段能否安全删除：返回"可以删"的理由，不能删返回 None。

    判定口径（就这一条，不做语义判断）：

    - ``covers`` 非空 → 不是空阶段，不动；
    - ``unmapped_covers`` 非空 → 这个阶段的覆盖面**归一不了**，我们根本无法
      判断它是不是在教一个真实缺口，信息不足，**不删**；
    - 其余空阶段 → 它覆盖不到任何高/中优先级缺口，删掉不损失任何学习目标。

    "没有独立价值"在这里就是"覆盖不到用户的任何一个待补缺口"，不含主观判断。
    """
    if stage.get("covers"):
        return None
    if stage.get("unmapped_covers"):
        return None
    dropped = list(stage.get("dropped_low_priority") or [])
    if dropped:
        return f"covers 里的 {dropped} 全是已满足/低优先级技能，阶段已无独立学习价值"
    return "covers 为空，未覆盖任何高/中优先级缺口"


def drop_empty_stages(stages: list, gaps: list, vocabulary) -> tuple[list[str], list[str]]:
    """删除没有独立价值的空阶段，返回 ``(处理说明, 保留告警)``。

    删除前提：删完仍要满足节点既有的最少阶段数 :data:`MIN_STAGES`。
    删不到这个下限就**整条回退、一个都不删**，并给出告警 ——
    宁可留一个空阶段，也不把学习路线删到不合规。

    调用方（learning_node）负责之后的编号重排与总周数复算。
    """
    removable: list[dict] = []
    keep: list[dict] = []
    reasons: dict[int, str] = {}
    for stage in stages:
        reason = droppable_empty_stage(stage)
        if reason is None:
            keep.append(stage)
        else:
            removable.append(stage)
            reasons[id(stage)] = reason

    if not removable:
        return [], []

    if len(keep) < MIN_STAGES:
        return [], [
            f"阶段「{stage.get('topic')}」{reasons[id(stage)]}，"
            f"但删掉后学习阶段只剩 {len(keep)} 个、低于下限 {MIN_STAGES}，"
            f"故保留该阶段并告警，不擅自删除"
            for stage in removable
        ]

    stages[:] = keep
    for index, stage in enumerate(stages, start=1):
        stage["stage"] = index
    notes = [
        f"已删除空阶段「{stage.get('topic')}」（{reasons[id(stage)]}）"
        for stage in removable
    ]
    notes.append(f"删除后学习路线剩 {len(stages)} 个阶段、共 {total_weeks(stages)} 周")

    # 删除后复检：被删阶段的 covers 本来就是空的，覆盖情况理论上不变，
    # 但仍然实检一遍并把结果报出来（不改任何东西，只报告）。
    for issue in check_coverage(stages, gaps, vocabulary):
        notes.append(f"删除阶段后复检覆盖情况：{issue}")
    return notes, []


# ── 轻量告警：covers 里的技能在两段文字里完全没被提到（问题 3）────────────
def skill_mention_terms(skill, vocabulary) -> set[str]:
    """判断"阶段有没有提到这项技能"用的提法集合。

    全部取自**既有结构**：规范技能名、名称按空格/斜杠拆开后的各部分、
    以及 :class:`SkillVocabulary` 里已维护的别名。不新造词表、不做分词、
    不引任何 NLP 依赖。
    """
    terms = {str(skill or "").strip().lower()}
    for part in re.split(r"[／/\s]+", str(skill or "")):
        part = part.strip().lower()
        if part:
            terms.add(part)
    if vocabulary is not None:
        for alias in vocabulary.aliases.get(skill) or ():
            alias = str(alias).strip().lower()
            if alias:
                terms.add(alias)
    return {t for t in terms if t}


def check_skill_mentions(stages: list, vocabulary) -> list[str]:
    """只告警：covers 里的技能在 goal 与 completion_criteria 里都没被提到。

    **这是一个"有没有提到"的检查，不是"学到什么程度"的语义检查。**

    刻意接受的局限（写在明处，避免误用）：

    - 名字/别名出现过就放过，哪怕写得再空（只写"掌握 LLM API"也算提到）；
    - 技能名里含"开发""服务"这类泛化词时容易判成"已提到" —— 宁漏报不误报，
      避免告警疲劳；
    - 因此它**只负责提示**，绝不据此修改或删除任何阶段，也不会伪造学习目标。

    要判断"写的内容是不是真的在教这项技能"，需要语义理解；按约束没有引入。
    """
    issues: list[str] = []
    for index, stage in enumerate(stages, start=1):
        text = (
            f"{stage.get('goal') or ''} {stage.get('completion_criteria') or ''}"
        ).lower()
        if not text.strip():
            continue  # 两段文字都空，属于另一类问题，不在本检查职责内
        for skill in stage.get("covers") or []:
            terms = skill_mention_terms(skill, vocabulary)
            if terms and not any(term in text for term in terms):
                issues.append(
                    f"阶段 {index} 的 covers 含「{skill}」，但 goal 与 completion_criteria "
                    f"都没有提到它；这项技能可能只挂在 covers 上、没有实际学习内容，请人工确认"
                )
    return issues


def check_duplicate_covers(stages: list, vocabulary) -> list[str]:
    """只告警：同一个技能被**多个**学习阶段重复覆盖。

    统计前先按规范技能名归一（复用 :func:`resolve_canonical`），否则
    "后端服务" 与 "后端 API 开发"、"LangChain" 与 "LangChain / LangGraph"
    这类同义写法会被当成两个技能而漏检。

    重复本身不一定是错的 —— "基础阶段先接触、进阶阶段再深化"是合理的，
    所以这里**只提示人工确认**：不删除任何技能、不合并阶段、不改动学习路线。
    """
    seen: dict[str, list[int]] = {}
    for index, stage in enumerate(stages, start=1):
        for cover in stage.get("covers") or []:
            raw = str(cover or "").strip()
            if not raw:
                continue
            canonical = resolve_canonical(raw, vocabulary) or raw
            stages_of = seen.setdefault(canonical, [])
            if index not in stages_of:
                stages_of.append(index)

    return [
        f"技能「{skill}」被多个学习阶段重复覆盖（阶段 {', '.join(str(i) for i in indexes)}）；"
        f"请确认这是有进阶关系的重复练习，而不是无意义的重复排期"
        for skill, indexes in seen.items()
        if len(indexes) > 1
    ]


def _levels_mentioned(text) -> set[str]:
    """文本里**明确写出**的等级词。"""
    body = str(text or "")
    return {level for level in SKILL_LEVELS if level in body}


def _level_from_guides(text, guides) -> str | None:
    """完成标准与知识库某等级的标准一致时，反推它对应的等级。

    小模型常直接抄知识库的等级标准，却不在文字里写"中级"二字；这时只能靠
    文本比对把它认出来，否则等级一致性根本查不出来。
    """
    body = str(text or "").strip()
    if not body or not guides:
        return None
    for level in SKILL_LEVELS:
        guide = str(guides.get(level, "")).strip()
        if not guide:
            continue
        if guide in body or (len(body) >= _MIN_GUIDE_MATCH_LEN and body in guide):
            return level
    return None


def check_level_consistency(stage: dict, gaps: list, base, vocabulary) -> list[str]:
    """阶段的目标等级是否自洽（S8）。

    三处必须一致：goal 说的等级、completion_criteria 对应的等级、
    所覆盖缺口在岗位要求里的等级。任何一处对不上都要报告。
    """
    lookup = _gap_lookup(gaps, vocabulary)
    covers = list(stage.get("covers") or [])
    target = _stage_target_level(stage, lookup)

    guides: dict[str, dict] = {}
    if base is not None and covers:
        found, _ = base.get_many(covers)
        for item in found:
            guides[item["skill"]] = item.get("level_guides") or {}

    goal_levels = _levels_mentioned(stage.get("goal"))
    criteria_levels = _levels_mentioned(stage.get("completion_criteria"))
    if not criteria_levels:
        inferred = {
            level
            for guide in guides.values()
            if (level := _level_from_guides(stage.get("completion_criteria"), guide))
        }
        criteria_levels = inferred

    issues: list[str] = []
    if goal_levels and criteria_levels and not (goal_levels & criteria_levels):
        issues.append(
            f"goal 说的等级 {sorted(goal_levels)} 与 completion_criteria 的等级 "
            f"{sorted(criteria_levels)} 不一致"
        )
    if target:
        for label, levels in (("goal", goal_levels), ("completion_criteria", criteria_levels)):
            if levels and target not in levels:
                issues.append(
                    f"{label} 的等级 {sorted(levels)} 与所覆盖缺口的岗位要求等级「{target}」不一致"
                )
    return issues


def total_weeks(stages: list) -> int:
    """学习路线总周数。非整数周按 0 计，不让脏数据把校验打断。"""
    total = 0
    for stage in stages:
        try:
            total += int(stage.get("estimated_weeks") or 0)
        except (TypeError, ValueError):
            continue
    return total


def check_total_weeks(stages: list, limit: int = MAX_TOTAL_WEEKS) -> list[str]:
    """总时长超上限时报告超出量——只报告，不删缺口。"""
    total = total_weeks(stages)
    if total <= limit:
        return []
    return [
        f"学习路线总时长 {total} 周，超过上限 {limit} 周（超出 {total - limit} 周）；"
        f"已保留全部高优先级缺口，没有用删减缺口的方式压时长，请人工评估是否拆成多个学期"
    ]


def validate_learning_plan(stages: list, gaps: list, vocabulary, base) -> list[str]:
    """跑完全部程序化校验，返回问题清单（含阶段级与全局）。"""
    # 等级一致性必须在 repair 之前算：repair 会把已满足/低优先级技能移出 covers，
    # 而"goal 说要高级、完成标准却只有中级"这类矛盾恰恰出现在这些阶段上
    # （报告里的阶段 1 就是 Python 已满足、goal 却写"高级特性"）。
    # covers 被清空后等级校验就没有参照物了，所以这里用**归一后的原始 covers** 先算一遍。
    level_issues: list[str] = []
    for index, stage in enumerate(stages, start=1):
        raw_covers, _, _ = normalize_covers(stage.get("covers"), vocabulary)
        probe = {**stage, "covers": raw_covers}
        for issue in check_level_consistency(probe, gaps, base, vocabulary):
            level_issues.append(f"阶段 {index}：{issue}")

    issues = repair_stages(stages, gaps, vocabulary)
    issues.extend(check_coverage(stages, gaps, vocabulary))
    issues.extend(check_total_weeks(stages))
    issues.extend(check_skill_mentions(stages, vocabulary))
    issues.extend(check_duplicate_covers(stages, vocabulary))
    issues.extend(level_issues)
    return issues


def learning_node(state: CareerState) -> dict:
    """LangGraph 节点：读取 skill_gaps / user_skills / target_job，写入 learning_plan。"""
    gaps = state.get("skill_gaps") or []
    if not gaps:
        raise ValueError("state 中缺少 skill_gaps，无法制定学习路线")

    vocabulary = _load_vocabulary()
    base = _load_skill_base()

    # 先把缺口技能名归一到规范技能名，知识库才查得到；查不到的显式列出来
    gap_skills = [g.get("skill") for g in gaps]
    mapping, unmapped = build_skill_mapping(gap_skills, vocabulary)
    canonical_skills = list(dict.fromkeys(mapping.values()))
    if unmapped:
        print(
            f"[Learning Agent] 警告：以下缺口无法归一为规范技能名，其能力标准不属于"
            f"知识库内容，不得伪造成知识库来源：{unmapped}",
            flush=True,
        )

    unmapped_block = (
        "、".join(unmapped) if unmapped else "（无，全部缺口都能在知识库里找到对应标准）"
    )
    prompt = PROMPT.format(
        target_job=state.get("target_job", "目标岗位"),
        gaps=_format_gaps(gaps),
        user_skills=_format_skills(state.get("user_skills") or []),
        skill_knowledge=_skill_knowledge_block(canonical_skills, base),
        unmapped_skills=unmapped_block,
    )
    plan = structured_invoke(prompt, LearningPlan)

    stages = [s.model_dump() for s in plan.stages]
    stages = dedupe_by(stages, key="topic")
    check_non_empty(stages, "Learning Agent 的学习阶段列表", minimum=2)

    # 按阶段号排序，防止模型乱序输出
    stages.sort(key=lambda s: s["stage"])
    for index, stage in enumerate(stages, start=1):
        stage["stage"] = index  # 阶段号重排，保证连续

    # 程序化修复（都在进入校验之前做，改完再校验）：模型只写文字，
    # 覆盖是否完整、等级措辞是否对齐，全由代码判定并动手。
    # 1) 归一 covers、剔掉已满足/低优先级技能
    repair_stages(stages, gaps, vocabulary)
    # 2) 清掉修完 covers 为空的阶段（删不动就保留并告警，不硬删）
    drop_notes, drop_warnings = drop_empty_stages(stages, gaps, vocabulary)
    for note in drop_notes:
        print(f"[Learning Agent] {note}", flush=True)
    for warning in drop_warnings:
        print(f"[Learning Agent] 警告：{warning}", flush=True)
    # 3) 防漏回路：高优先级缺口一个没被覆盖就由代码补一个阶段出来
    for note in backfill_uncovered_gaps(stages, gaps, vocabulary, base):
        print(f"[Learning Agent] {note}", flush=True)
    # 4) 等级措辞向缺口要求等级对齐（放在补漏之后，补出来的阶段一并处理）
    for note in align_stage_levels(stages, gaps, vocabulary, base):
        print(f"[Learning Agent] {note}", flush=True)

    # 终检：剩下的每一条都是代码改不掉的，如实报警
    issues = validate_learning_plan(stages, gaps, vocabulary, base)
    for issue in issues:
        print(f"[Learning Agent] 警告：{issue}", flush=True)

    log("Learning Agent")
    return check_update({"learning_plan": stages}, "Learning Agent")
