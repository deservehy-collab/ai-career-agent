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


def show(title: str, data) -> None:
    print(f"\n{'=' * 10} {title} {'=' * 10}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


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
    )

    show("用户能力", result.get("user_skills", []))
    show_retrieval(result)
    show("岗位要求", result.get("job_requirements", []))
    show("能力差距", result.get("skill_gaps", []))
    show("学习路线", result.get("learning_plan", []))
    show("项目路线", result.get("project_plan", []))
    show("最终方案", build_final_plan(result))
