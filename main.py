"""AI 大学生成长 / 就业智能规划系统 —— 第五阶段：LangGraph 完整工作流"""

import json
import sys

from agents.growth_agent import (
    OUTCOME_ALL_DUPLICATES,
    OUTCOME_BLOCKED,
    OUTCOME_GATE_UNAVAILABLE,
    OUTCOME_INVALID_EVENTS,
    OUTCOME_NO_EVENTS,
    OUTCOME_NO_UPGRADE,
    OUTCOME_STORE_UNREADABLE,
    OUTCOME_UPGRADED,
)
from agents.growth_rules import (
    GATE_BLOCKED,
    GATE_NOT_COVERED,
    GATE_PASSED,
    GATE_UNAVAILABLE,
    KB_STATUS_LOAD_FAILED,
    validate_event,
)
from agents.growth_store import WRITE_REFUSED
from graph.workflow import build_final_plan, workflow

# Windows 控制台默认可能是 GBK，强制 UTF-8 避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

user_profile = {
    "major": "计算机科学与技术",
    "grade": "大三",
    "skills": ["Python", "LangChain", "LangGraph", "RAG", "Docker"],
    "projects": ["RAG知识库问答系统"],
}

target_job = "AI应用开发工程师"

# 阶段四：真实 JD 定向匹配的可选入口目标。
# - 传 jd_source_id（如 "jd_hundsun_001"）：精确匹配某一份真实 JD，优先级最高；
# - 传 target_company（如 "恒生电子" 或 "hundsun"）：公司级匹配；
# - 都不传：保持阶段二以来默认的跨公司概览行为。
# 两者同时传入时必须归属一致，否则入口解析会明确报错（见 retrieval_agent）。
jd_source_id = None
target_company = None  # 例如 "恒生电子" 或 "hundsun" 解析出 hundsun
extra_input = {k: v for k, v in {
    "jd_source_id": jd_source_id,
    "target_company": target_company,
}.items() if v}


def show(title: str, data) -> None:
    print(f"\n{'=' * 10} {title} {'=' * 10}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


# 终端展示用的学习阶段字段：只挑原有业务字段
LEARNING_STAGE_FIELDS = (
    "stage",
    "topic",
    "goal",
    "covers",
    "prerequisite",
    "completion_criteria",
    "estimated_weeks",
)


def public_learning_plan(stages: list) -> list:
    """把学习路线投影成**只含原有业务字段**的展示形态。

    阶段字典里还有 ``skill_mapping`` / ``unmapped_covers`` /
    ``dropped_low_priority`` 等内部追踪字段 —— 它们在 state 里**继续保留**
    （下游与排查都要用），只是在终端展示这一层被过滤掉，避免把内部口径
    混进给用户看的输出。这里**只做投影，不删任何内部数据**。

    缺失字段一律按 None 处理：``dropped_low_priority`` 本来就是"非空才写"，
    空路线也不能让展示炸掉。
    """
    return [
        {key: stage.get(key) for key in LEARNING_STAGE_FIELDS}
        for stage in (stages or [])
        if isinstance(stage, dict)
    ]


def show_jd_match(match: dict) -> None:
    """展示阶段四的真实 JD 定向匹配结论（纯展示，复用 jd_match 结果）。"""
    print(f"\n{'=' * 10} 真实 JD 匹配 {'=' * 10}")
    if not match:
        print("（没有 JD 匹配结论）")
        return

    print(f"总体结论：{match.get('overall', 'unknown')}")
    print(f"参与匹配 JD 数量：{match.get('matched_jd_count', 0)}")
    print(f"目标 JD（source_id）：{match.get('jd_target') or '未指定（跨公司概览）'}")

    # 计数口径分三层，不能把"有证据归属数"说成"可判定数"：
    # 有证据归属 = 归属该目标 + 能回查到证据；可判定 = 其中还能对上能力差距的。
    judged = match.get("requirement_judged", 0)
    print(f"有证据归属的岗位要求：{match.get('requirement_total', 0)} 项")
    print(f"  可判定（计入统计）：{judged} 项")
    print(f"    - 已满足：{match.get('requirement_satisfied', 0)} 项")
    print(f"    - 存在差距：{match.get('requirement_shortfall', 0)} 项")
    print(f"  证据不足（不计入统计，也不进分母）：{match.get('requirement_orphan', 0)} 项")

    # 满足率的分母只能是可判定要求数；分母为 0 时不出百分比
    rate = match.get("match_rate")
    if rate is None:
        print("满足率：无可判定要求，本次不出满足率")
    else:
        print(f"满足率：{rate:.0%}（分母 = 可判定要求 {judged} 项）")

    hard_blocks = match.get("hard_blocks") or []
    if hard_blocks:
        print(
            f"硬性缺口候选（{len(hard_blocks)} 项）"
            f"——supported = 技能名与证据完全同名；partially_supported = 仅别名/语义相关，"
            f"证据强度弱于前者，不等于完全确认："
        )
        for block in hard_blocks:
            print(
                f"  - {block.get('skill')}"
                f"（重要性 {block.get('importance')}，"
                f"要求等级 {block.get('required_level')}，"
                f"证据强度 {block.get('evidence_status') or '未知'}）"
            )

    key_gaps = match.get("key_gaps") or []
    if key_gaps:
        print("关键差距（按优先级）：")
        for gap in key_gaps:
            print(
                f"  - {gap.get('skill')}"
                f"（重要性 {gap.get('importance')}，优先级 {gap.get('priority')}）"
            )

    warning = match.get("jd_source_warning")
    if warning:
        print(f"来源提示：{warning}")


def show_retrieval(result: dict) -> None:
    """展示岗位知识库检索结果（纯展示，不参与后续规划计算）。"""
    print(f"\n{'=' * 10} 岗位知识库检索 {'=' * 10}")

    evidence = result.get("job_evidence") or []
    diagnostics = result.get("retrieval_diagnostics") or {}

    print(f"检索状态：{result.get('retrieval_status', '未执行')}")
    print(f"证据数量：{len(evidence)} 条")
    if diagnostics.get("match_kind"):
        print(f"命中路径：{diagnostics['match_kind']}")

    scope = diagnostics.get("sample_scope")
    if scope:
        companies = "、".join(scope.get("companies") or []) or "未标注"
        print(f"样本范围：{scope.get('jd_count')} 份 JD（{companies}）")
        if scope.get("caveat"):
            print(f"          {scope['caveat']}")
    if diagnostics.get("reason"):
        print(f"说明：{diagnostics['reason']}")
    for error in diagnostics.get("errors") or []:
        print(f"警告：{error}")

    if not evidence:
        print("（没有可用证据，已降级继续；岗位要求仍由 Job Agent 生成）")
        return

    for index, item in enumerate(evidence, start=1):
        importance = item.get("importance")
        importance = f"{importance}/5" if importance is not None else "未知"
        print(
            f"  {index}. [{item.get('company_slug') or '未标注公司'}] {item.get('skill')}"
            f"｜要求类型：{item.get('requirement_type')}"
            f"｜重要程度：{importance}"
        )
        if item.get("companies"):
            print(f"      覆盖公司：{'、'.join(item['companies'])}（仅本样本内）")
        print(f"      原文出处：{item.get('context')}｜{item.get('note')}")


# ── 阶段五：动态能力成长的输入与展示 ────────────────────────────────────
# outcome → 给人看的一句话（键取自 agents/growth_agent.py 的常量，避免两处写法漂移）
OUTCOME_LABELS = {
    OUTCOME_NO_EVENTS: "本轮没有成长事件",
    OUTCOME_UPGRADED: "有技能等级提升",
    OUTCOME_NO_UPGRADE: "有事件，但没有产生等级变化",
    OUTCOME_ALL_DUPLICATES: "事件都是历史重复，未重复升级",
    OUTCOME_BLOCKED: "升级被前置技能门禁拦下",
    OUTCOME_GATE_UNAVAILABLE: "知识库不可用，前置门禁未执行",
    OUTCOME_INVALID_EVENTS: "事件不合法，已跳过",
    OUTCOME_STORE_UNREADABLE: "成长历史无法读取（已按 profile 基线继续）",
}

# 门禁结论 → 给人看的一句话
GATE_LABELS = {
    GATE_PASSED: "已通过（技能已收录且前置齐备）",
    GATE_NOT_COVERED: "已跳过（该技能未收录等级标准）",
    GATE_UNAVAILABLE: "未执行（知识库加载失败）",
    GATE_BLOCKED: "被拦截（前置技能不足）",
}

_GROWTH_TYPE_CHOICES = {"1": "learning", "2": "project"}
_GROWTH_TYPE_LABELS = {"learning": "学习成果", "project": "项目成果"}
_YES_WORDS = ("y", "yes", "是")
_SKIP_WORDS = ("", "n", "no", "否", "跳过", "s")


def _ask(input_fn, prompt: str) -> str:
    """读一行输入并去掉首尾空白。input_fn 可注入，便于自动化测试。"""
    return str(input_fn(prompt) or "").strip()


def _ask_growth_event(input_fn, index: int):
    """问一条成长成果。返回事件 dict；用户放弃时返回 ``None``。

    只收集 ``validate_event()`` 要求的字段（type / title / skills / evidence），
    **不提供"把技能升到几级"的输入** —— 等级一律由 agents/growth_rules.py 按
    「一档封顶 + 证据分级 + 前置技能门禁」判定，用户只负责提供"做了什么"这类事实。

    每个字段**各自重问**：某一项填错只重问那一项，不会把整份表单推倒重来。
    """
    print(f"\n-- 第 {index} 条成果（类型处直接回车即跳过）--")
    print("  1 = 学习成果（本轮最高只能升到 初级）")
    print("  2 = 项目成果（本轮最高只能升到 中级）")

    while True:
        kind = _ask(input_fn, "  类型 [1/2，回车跳过]：").lower()
        if kind in _SKIP_WORDS:
            return None
        if kind in _GROWTH_TYPE_CHOICES:
            break
        print(f"  ✗ 类型只能填 1 或 2，收到 {kind!r}，请重新输入")

    while True:
        title = _ask(input_fn, "  成果标题（如：完成 RAG 知识库问答系统）：")
        if title:
            break
        print("  ✗ 标题不能为空，请重新输入")

    while True:
        raw_skills = _ask(input_fn, "  涉及技能（顿号或逗号分隔，如：RAG、Embedding）：")
        skills = [
            part.strip()
            for part in raw_skills.replace("，", "、").replace(",", "、").split("、")
            if part.strip()
        ]
        if skills:
            break
        print("  ✗ 至少要填一项技能，请重新输入")

    while True:
        evidence = _ask(input_fn, "  证据（具体做了什么、有什么产出）：")
        if evidence:
            break
        print("  ✗ 证据不能为空 —— 只有标题不会带来任何升级")

    event = {
        "type": _GROWTH_TYPE_CHOICES[kind],
        "title": title,
        "skills": skills,
        "evidence": evidence,
    }
    # 四个字段已逐个把关，这里正常不会再失败；留着是为了万一口径变了能明确报出来
    _, reason = validate_event(event)
    if reason:
        print(f"  ✗ 这条成果不合法：{reason}（已跳过）")
        return None

    print(
        f"  ✓ 已记录：{_GROWTH_TYPE_LABELS[event['type']]}「{title}」"
        f"（{'、'.join(skills)}）"
    )
    return event


def collect_growth_events(input_fn=input) -> list:
    """交互式收集本轮新增的学习 / 项目成果。直接回车即跳过，不记录任何成长。

    返回值直接塞进 ``workflow.invoke(...)`` 的 ``growth_events`` 字段；
    跳过时返回空列表，工作流行为与不带成长事件时一致。
    """
    print(f"\n{'=' * 10} 记录成长成果 {'=' * 10}")
    print("可以登记本轮新完成的学习或项目成果，系统会据此重新评估能力与路线。")
    answer = _ask(input_fn, "现在要记录新的成果吗？[y/N]：").lower()
    if answer not in _YES_WORDS:
        print("（已跳过：本轮不记录成长事件，能力维持现状）")
        return []

    events: list = []
    while True:
        event = _ask_growth_event(input_fn, len(events) + 1)
        if event is None:
            break
        events.append(event)
        if _ask(input_fn, "还要再记一条吗？[y/N]：").lower() not in _YES_WORDS:
            break

    if not events:
        print("（已跳过：本轮不记录成长事件，能力维持现状）")
    else:
        print(f"\n共记录 {len(events)} 条成长成果，将交给成长节点判定等级。")
    return events


def show_growth_result(growth: dict) -> None:
    """展示动态能力成长结果（纯展示，复用 growth_diff 的真实字段）。"""
    print(f"\n{'=' * 10} 动态能力成长 {'=' * 10}")
    if not growth:
        print("（本轮没有成长记录）")
        return

    outcome = growth.get("outcome")
    print(f"本轮结果：{OUTCOME_LABELS.get(outcome, outcome or '未知')}")
    print(f"收到成果事件：{growth.get('events_received', 0)} 条")
    if growth.get("knowledge_base_status") == KB_STATUS_LOAD_FAILED:
        print("⚠ 技能知识库加载失败：本次**没有执行**前置技能门禁，升级结果可能偏宽松")

    # 1) 技能等级变化
    updates = growth.get("level_changes") or []
    if updates:
        print(f"\n技能等级变化（{len(updates)} 项）：")
        for item in updates:
            print(f"  - {item.get('skill')}：{item.get('from') or '无'} → {item.get('to')}")
            print(f"      依据：{item.get('reason')}")
            print(f"      来源成果：{item.get('source')}")
            print(f"      前置门禁：{GATE_LABELS.get(item.get('gate_status'), item.get('gate_status') or '未知')}")
            if item.get("gate_unavailable"):
                print("      ⚠ 该升级没有经过前置技能校验，不能当成已通过门禁")
            for note in item.get("notes") or []:
                print(f"      提示：{note}")
    else:
        print("\n技能等级变化：无 —— 本轮没有任何技能的等级被提升（原因见下面的分类）")

    # 2) 被门禁拦下的升级
    blocked = growth.get("blocked_upgrades") or []
    if blocked:
        print(f"\n被前置门禁拦下的升级（{len(blocked)} 项）：")
        for item in blocked:
            missing = "、".join(item.get("missing_prerequisites") or []) or "（未给出）"
            print(
                f"  - {item.get('skill')}：{item.get('current_level') or '无'}"
                f" → 本可升到 {item.get('candidate_level')}"
            )
            print(f"      缺前置：{missing}")
            print(f"      原因：{item.get('reason')}")

    # 3) 重复 / 非法 / 未映射 / 未升级的候选
    duplicates = growth.get("duplicates") or []
    if duplicates:
        print(f"\n重复成果（{len(duplicates)} 条，已跳过以免重复升级）：")
        for item in duplicates:
            print(f"  - {item.get('title')}（指纹 {item.get('fingerprint')}）")

    invalid = growth.get("invalid_events") or []
    if invalid:
        print(f"\n不合法成果（{len(invalid)} 条，已跳过）：")
        for item in invalid:
            print(f"  - 第 {item.get('index')} 条：{item.get('reason')}")

    unmapped = growth.get("unmapped_skills") or []
    if unmapped:
        print(f"\n无法归一的技能名（{len(unmapped)} 处，未参与升级）：")
        for item in unmapped:
            print(f"  - 来自「{item.get('title')}」：{'、'.join(item.get('skills') or [])}")

    skipped = growth.get("skipped") or []
    if skipped:
        print(f"\n未升级的候选（{len(skipped)} 项）：")
        for item in skipped:
            print(f"  - {item.get('skill')}（{item.get('title')}）：{item.get('reason')}")

    # 4) 历史写入状态：True / False / None / 字段缺失 四种情况分开说，
    #    绝不把"没有发生写入"说成写入成功
    print("\n成长历史：")
    written = growth.get("history_written")
    status = growth.get("history_write_status")
    if written is True:
        print(f"  已写入 runs/growth.json（写入状态：{status}）")
    elif written is False and status == WRITE_REFUSED:
        print("  **未写入** —— 存储层拒绝了本次写入，原文件很可能已损坏且未被覆盖")
    elif written is False and status is None:
        print("  本轮无需写入（没有产生需要记录的候选成果）")
    elif written is False:
        print(f"  **未写入**（写入状态：{status}）")
    else:
        print("  写入状态未知（本条记录里没有 history_written 字段）")

    for warning in growth.get("warnings") or []:
        print(f"  提示：{warning}")


def show_gap_change(comparison: dict, level_changes=None) -> None:
    """展示成长前后的岗位缺口变化。

    **必须**传 ``final_plan["growth_diff"]["gap_comparison"]``：成长节点自己写的那个
    ``gap_comparison`` 永远是"不可比"的（它跑在 job 节点之前，拿不到岗位要求），
    真正的对比是 ``build_final_plan()`` 在 assessment 之后算出来的。
    """
    print(f"\n{'=' * 10} 岗位缺口变化 {'=' * 10}")
    if not comparison:
        print("（没有缺口对比结果）")
        return
    if comparison.get("status") != "computed":
        print(f"本次无法比较成长前后的岗位缺口：{comparison.get('reason') or '原因未知'}")
        return

    counts = comparison.get("gap_count") or {}
    print(
        f"参与对比的岗位要求：成长前 {counts.get('before', '?')} 条"
        f" → 成长后 {counts.get('after', '?')} 条"
    )

    newly = comparison.get("newly_satisfied") or []
    appeared = comparison.get("newly_appeared") or []
    resolved = comparison.get("resolved_gaps") or []
    print(f"新满足的缺口：{len(newly)} 项" + (f"（{'、'.join(newly)}）" if newly else ""))
    print(f"新出现的缺口：{len(appeared)} 项" + (f"（{'、'.join(appeared)}）" if appeared else ""))
    print(f"已消除的缺口：{len(resolved)} 项" + (f"（{'、'.join(resolved)}）" if resolved else ""))

    changes = comparison.get("changes") or []
    if changes:
        print("具体变化：")
        for item in changes:
            print(
                f"  - {item.get('skill')}：{item.get('status_before')} → {item.get('status_after')}"
                f"（优先级 {item.get('priority_before')} → {item.get('priority_after')}）"
            )
    else:
        print("具体变化：无 —— 各缺口的状态与优先级都与成长前相同")
        if level_changes:
            names = "、".join(str(u.get("skill")) for u in level_changes)
            print(
                f"  说明：技能等级**确实提升了**（{names}），但还没跨过岗位要求的门槛，"
                f"所以缺口状态未变；技能成长见上面的「动态能力成长」一节。"
            )


def public_final_plan(plan: dict) -> dict:
    """最终方案的展示投影：``growth_diff`` 由专门函数展示，这里不再整份原样输出。

    只做投影，不改动 ``final_plan`` 本身。
    """
    return {key: value for key, value in (plan or {}).items() if key != "growth_diff"}


if __name__ == "__main__":
    print("开始执行 LangGraph 工作流...")

    # 阶段五：先收集本轮新完成的学习 / 项目成果（直接回车即跳过）
    growth_events = collect_growth_events()

    result = workflow.invoke(
        {
            "user_profile": user_profile,
            "target_job": target_job,
            "growth_events": growth_events,
        }
        | extra_input
    )

    show("用户能力", result.get("user_skills", []))
    show_retrieval(result)
    show("岗位要求", result.get("job_requirements", []))
    show("能力差距", result.get("skill_gaps", []))
    show("学习路线", public_learning_plan(result.get("learning_plan", [])))
    show("项目路线", result.get("project_plan", []))

    # 汇总只算一次：原计划、JD 匹配与成长差异都来自这一份结果
    final_plan = build_final_plan(result)
    growth = final_plan.get("growth_diff") or {}

    show("最终方案", public_final_plan(final_plan))
    show_jd_match(final_plan.get("jd_match"))
    show_growth_result(growth)
    show_gap_change(growth.get("gap_comparison"), growth.get("level_changes"))