"""Retrieval Agent：把岗位知识库（RAG）的检索结果接进职业规划工作流。

定位
----
本节点只负责"取事实"，不做任何判定，也不写 ``user_skills``：

- 输入：state 里的 ``target_job``（查询内容）与可选的 ``target_company``（限定公司）；
- 输出：``job_evidence``（岗位知识库里的原始证据）、``retrieval_status``、
  ``retrieval_diagnostics``。

检索逻辑全部委托给 ``agents/retriever.py``，本模块只做"调用 + 降级 + 组装 state"，
不复制也不改写检索行为。

降级原则
--------
岗位知识库是**增强**而不是**必需**：缺了它，profile → job → assessment → learning
→ project 这条链路依然成立。所以索引缺失、Ollama 未启动、公司名无法识别、
后端抛异常等情况一律降级继续 —— 只把状态与原因写进 ``retrieval_status`` /
``retrieval_diagnostics``，绝不中断整个规划流程。

唯一会抛异常的情况是 ``target_job`` 缺失：这属于调用方错误，且下游 job 节点
同样会因此报错，提前在这里拦下来能给出更准确的错误信息。

阶段四补充
----------
指定 ``jd_source_id``（精确匹配某一份真实 JD）时，``jd_source_id`` 与可选的
``target_company`` 会先解析成单一目标：source_id 不存在、该 JD 缺 ``company_slug``、
公司名无法识别、或两个参数指向不同公司，都属于调用方参数错误，**在 try 之外
明确报错**，不得吞成普通检索失败。``target_company`` 单独使用时不受影响，
仍按上面的降级原则处理（这是阶段二以来的既有行为）。

证据 ≠ 学生能力
---------------
``job_evidence`` 描述的是**岗位（JD）说了什么**，``user_skills`` 描述的是
**学生已经掌握什么**，两者是不同性质的数据，不得互相写入 —— 尤其不能因为
岗位要求里出现某技能，就把它当成学生已具备的技能。
"""

from __future__ import annotations

from agents.jd_match import resolve_target
from agents.retriever import (
    DEFAULT_JOB_ID,
    STATUS_MATCHED,
    STATUS_NO_SOURCE,
    JobKnowledgeRetriever,
    RetrieveRequest,
)
from agents.utils import log
from graph.state import CareerState, check_update

# 可替换的检索器：默认惰性创建（构造时不连接 Chroma / Ollama），测试可注入内存替身
_retriever: JobKnowledgeRetriever | None = None


def set_retriever(retriever: JobKnowledgeRetriever | None) -> None:
    """注入检索器（测试用）。传 None 表示下次调用时重建默认后端。"""
    global _retriever
    _retriever = retriever


def get_retriever() -> JobKnowledgeRetriever:
    """取检索器实例；默认后端是惰性的，直到真正发起检索才连接服务。"""
    global _retriever
    if _retriever is None:
        _retriever = JobKnowledgeRetriever()
    return _retriever


def retrieval_node(state: CareerState) -> dict:
    """LangGraph 节点：按目标岗位检索岗位知识库，写入检索结果。

    检索不出东西（``no_source`` / ``not_mentioned`` / ``ambiguous``）或后端出错时，
    返回空的 ``job_evidence`` 并说明原因，让后续节点照常执行。
    """
    target_job = (state.get("target_job") or "").strip()
    if not target_job:
        raise ValueError("state 中缺少 target_job，无法检索岗位知识库")

    company = state.get("target_company")
    company = str(company).strip() if company else None
    jd_source_id = state.get("jd_source_id")
    jd_source_id = str(jd_source_id).strip() if jd_source_id else None

    # 阶段四：入口目标解析。
    #
    # 只传 target_company（不传 jd_source_id）时**不走解析**：原样透传给 retriever，
    # 与阶段二逐字一致 —— 公司名无法识别时由 retriever 抛错、下面 except 降级继续。
    #
    # 指定了 jd_source_id 时先在 try 之外解析：source_id 不存在、解析不出归属公司、
    # 或与 target_company 指向不同公司，都属于**调用方参数错误**，必须明确报错，
    # 不得吞成普通检索失败。
    if jd_source_id:
        target = resolve_target(jd_source_id, company)
        request_company = target["company_slug"]
        request_source = target["source_id"]
    else:
        request_company = company
        request_source = None

    try:
        result = get_retriever().retrieve(
            RetrieveRequest(
                query=target_job, company=request_company, job_id=DEFAULT_JOB_ID,
                source_id=request_source,
            )
        )
        evidence = list(result.evidence or [])
        status = result.status
        diagnostics = dict(result.diagnostics or {})
        if status != STATUS_MATCHED:
            print(
                f"[Retrieval Agent] 未获得可用证据：status={status}"
                f"（{diagnostics.get('reason') or '无原因说明'}），已降级继续",
                flush=True,
            )
    except Exception as exc:  # 检索无论怎么失败，都不能拖垮整条流水线
        detail = f"{type(exc).__name__}: {exc}"
        reason = "invalid_request" if isinstance(exc, ValueError) else "backend_error"
        print(f"[Retrieval Agent] 警告：检索未完成，已降级继续（{detail}）", flush=True)
        evidence = []
        status = STATUS_NO_SOURCE
        diagnostics = {"job_id": DEFAULT_JOB_ID, "reason": reason, "errors": [detail]}

    log("Retrieval Agent")
    return check_update(
        {
            "job_evidence": evidence,
            "retrieval_status": status,
            "retrieval_diagnostics": diagnostics,
        },
        "Retrieval Agent",
    )