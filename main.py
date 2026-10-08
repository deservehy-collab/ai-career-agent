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


if __name__ == "__main__":
    print("开始执行 LangGraph 工作流...")

    result = workflow.invoke(
        {
            "user_profile": user_profile,
            "target_job": target_job,
        }
    )

    show("用户能力", result.get("user_skills", []))
    show("岗位要求", result.get("job_requirements", []))
    show("能力差距", result.get("skill_gaps", []))
    show("学习路线", result.get("learning_plan", []))
    show("项目路线", result.get("project_plan", []))
    show("最终方案", build_final_plan(result))
