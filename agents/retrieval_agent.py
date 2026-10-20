"""Retrieval Agent：把用户粘贴的招聘要求原文整理成逐句依据。

定位
----
本节点只负责"取事实"，不做任何判定，也不写 ``user_skills``：

- 输入：state 里的 ``jd_text``（用户当场复制的招聘要求原文）；
- 输出：``job_evidence``（一句一条的原话记录）、``retrieval_status``、
  ``retrieval_diagnostics``。

切句是纯文本操作，**不连接任何检索后端**：Ollama 只负责后面那几次推理，
这一步的等待时间为零。

没有原文时如实交出空证据
------------------------
``jd_text`` 为空、或原文里一句可用的都没切出来（比如只粘了个标题）时，
本节点返回空 ``job_evidence`` 并写清原因 —— **不**假装"有依据"。
下游 job 节点会把每条要求如实标成 ``model_supplement``，前端整栏标灰、
不给匹配度百分比。宁可明说"这是模型推断"，也不拿别的岗位的旧资料冒充证据。

证据 ≠ 学生能力
---------------
``job_evidence`` 描述的是**招聘方要什么**，``user_skills`` 描述的是
**学生已经掌握什么**，两者性质不同，不得互相写入 —— 尤其不能因为
岗位要求里出现某技能，就把它当成学生已具备的技能。
"""

from __future__ import annotations

from agents.user_jd import USER_JD_SOURCE_ID, chunk_user_jd
from agents.utils import log
from graph.state import CareerState, check_update

#: 依据来自用户当场粘贴的原文（最硬的一档：逐条能反查到原话）。
STATUS_USER_PASTED = "user_pasted"

#: 本次没有任何原文可用 —— 岗位要求将全部由模型推断。
STATUS_NO_SOURCE = "no_source"

_SOURCE_NOTE = "招聘方要求的原文，一句一条"


def _empty_update(reason: str, note: str) -> dict:
    """交出空证据 + 如实说明原因，让下游把结论标成"模型推断"。"""
    print(f"[Retrieval Agent] 警告：{note}，岗位要求将退化为模型推断（已如实标注）", flush=True)
    return check_update(
        {
            "job_evidence": [],
            "retrieval_status": STATUS_NO_SOURCE,
            "retrieval_diagnostics": {"reason": reason, "source_id": USER_JD_SOURCE_ID, "note": note},
        },
        "Retrieval Agent",
    )


def retrieval_node(state: CareerState) -> dict:
    """LangGraph 节点：把粘贴的招聘要求原文切成逐句依据写进 state。"""
    target_job = (state.get("target_job") or "").strip()
    if not target_job:
        raise ValueError("state 中缺少 target_job，无法确认这份原文对应哪个岗位")

    jd_text = str(state.get("jd_text") or "").strip()
    if not jd_text:
        return _empty_update("no_jd_text", "本次没有粘贴招聘要求原文")

    records, dropped = chunk_user_jd(jd_text)
    if not records:
        return _empty_update(
            "user_jd_empty", "粘贴的原文过短或全是标题序号，没切出可用句子"
        )

    log("Retrieval Agent")
    return check_update(
        {
            "job_evidence": records,
            "retrieval_status": STATUS_USER_PASTED,
            "retrieval_diagnostics": {
                "job_id": USER_JD_SOURCE_ID,
                "source_id": USER_JD_SOURCE_ID,
                "match_kind": "user_pasted",
                "scope_count": len(records),
                "dropped_sentences": dropped,
                "reason": _SOURCE_NOTE,
            },
        },
        "Retrieval Agent",
    )
