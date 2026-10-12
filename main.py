"""AI 大学生成长 / 就业智能规划系统 —— 第五阶段：LangGraph 完整工作流"""

import json
import sys

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


if __name__ == "__main__":
    print("开始执行 LangGraph 工作流...")

    result = workflow.invoke(
        {
            "user_profile": user_profile,
            "target_job": target_job,
        }
        | extra_input
    )

    show("用户能力", result.get("user_skills", []))
    show_retrieval(result)
    show("岗位要求", result.get("job_requirements", []))
    show("能力差距", result.get("skill_gaps", []))
    show("学习路线", public_learning_plan(result.get("learning_plan", [])))
    show("项目路线", result.get("project_plan", []))

    # 汇总只算一次：原计划与 JD 匹配来自同一份结果，避免重复计算
    final_plan = build_final_plan(result)
    show("最终方案", final_plan)
    show_jd_match(final_plan.get("jd_match"))