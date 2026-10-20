"""业务编排层：把 HTTP 请求翻译成对 ``agents/`` 既有函数的调用。

本模块**不重新实现**任何六阶段规则，全部委托：

============================================  ==========================================
接口需求                                      复用的既有函数
============================================  ==========================================
任务完成 + 证据                               ``agents.growth_loop.process_task_completion``
待处理成长成果                                ``agents.growth_loop.pending_growth_events``
下一轮成长规划                                ``pending_growth_events`` + ``graph.workflow.workflow``
任务 / 轮次查询                               ``agents.loop_store.LoopStore``
成长历史查询                                  ``agents.growth_store.GrowthStore``
============================================  ==========================================

三条不可动摇的边界（对应 tests/ 里的四个 API 测试）：

1. **分析只读** —— 由 ``backend.analyze._isolated_growth_store`` 保证。
2. **任务完成只写 loop.json** —— 升级只是"只读预览"，正式落盘只发生在
   下一轮规划时由 ``growth_node`` 走正式路径写入。
3. **查询不改动磁盘** —— 待办成果查询前后，两个 store 文件逐字节不变。
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from agents.growth_loop import pending_growth_events, process_task_completion
from agents.growth_store import GrowthStore
from agents.loop_store import (
    COMPLETE_ALREADY,
    COMPLETE_INVALID_TASK_ID,
    COMPLETE_OK,
    COMPLETE_UNKNOWN_TASK,
    KIND_LEARNING,
    KIND_PROJECT,
    STATUS_CORRUPT as LOOP_STATUS_CORRUPT,
    STATUS_EMPTY as LOOP_STATUS_EMPTY,
    STATUS_OK as LOOP_STATUS_OK,
    STATUS_SCHEMA_MISMATCH as LOOP_STATUS_SCHEMA_MISMATCH,
    STATUS_UNREADABLE as LOOP_STATUS_UNREADABLE,
    TASK_COMPLETED,
    TASK_PENDING,
    WRITE_OK,
    LoopStore,
    LoopStoreError,
)
from agents.project_knowledge import ProjectKnowledgeBase
from agents.skill_knowledge import SkillKnowledgeBase
from backend import config
from backend.analyze import jsonable, use_growth_store, workflow

__all__ = [
    "Stores", "complete_task", "list_pending", "run_next_round", "list_tasks",
    "growth_history", "health", "_run_next_round", "add_manual_event",
    "run_analyze_and_save",
]

#: 断线原因（供 warning 文案使用）
_NO_EVENTS_WARNING = (
    "本次没有「已完成但还没交给成长节点」的成果，未生成新一轮计划"
    "（不伪造轮次，也不伪造成长记录）"
)


@dataclass
class Stores:
    """一次请求会用到的两个存储入口（由 ``backend.deps.create_stores`` 构造）。

    两个 store 都是**无内存状态**的：每次调用重新读盘、改副本、原子写，
    所以"每个请求新建一个实例"是安全的。
    """

    growth: GrowthStore
    loop: LoopStore


# ── 任务完成（只写 loop.json）────────────────────────────────────────────

# 进程内互斥锁：保护 ``loop.json`` 的**全部**读—改—写。
#
# 为什么需要
# ----------
# ``LoopStore`` 的每次写入都是「``load()`` 读全量 → 深拷贝改副本 → ``_write()`` 原子
# 替换」。``_write`` 的"原子"只保证**文件替换**不半途而废，**不保证两次读—改—写之间
# 不互相覆盖**：两个线程各自读到同一份基线，后写的那个会把先写的整条丢掉（丢失更新）。
# 存储层自身没有任何锁（``agents/loop_store.py`` 不 import threading），所以在**服务层**
# 补这把锁。
#
# 保护范围：按"写入方"划，不按"接口名"划
# ----------------------------------------
# 会写 ``loop.json`` 的路径有四条，**四条都在锁内**，缺一条就前功尽弃：
#
# 1. :func:`complete_task` —— ``mark_completed``（HTTP 请求线程，会真正并发）
# 2. :func:`add_manual_event` —— ``append_round`` + ``mark_completed`` 两段
# 3. :func:`_run_next_round` —— 下一轮规划末尾的 ``append_round``（后台工作线程）
# 4. :func:`run_analyze_and_save` —— 首轮任务的 ``append_round``（后台工作线程）
#
# 临界区只包住**读写本身**（毫秒级），绝不把 ``workflow.invoke`` 那几分钟的模型推理
# 放进去 —— 否则一次「生成下一轮」会把同时提交的任务完成堵死。临界区里只做
# 纯规则计算与文件读写：升级预览读 YAML 词表与技能库，**不调模型**。
#
# 边界（不要误用）
# ----------------
# - **不是跨进程锁**：只对本进程内的线程有效。服务仍必须 ``--workers 1``，
#   多 worker / 同时跑 ``main.py`` CLI 时这把锁形同虚设（根治要靠业务数据进数据库）。
# - **不保护"读到的基线有多新"**：``_run_next_round`` 开头的 ``pending_growth_events``
#   与推理之间可能有新完成的任务落盘，那条成果**不会**丢 —— 指纹没进成长历史，
#   下一次「生成下一轮」仍会排队（见 agents/growth_loop.py 的判据）。
# - 用 ``RLock`` 而非 ``Lock``：同一线程重入不会自锁死，互斥性不受影响。
_STORE_WRITE_LOCK = threading.RLock()


def complete_task(
    stores: Stores,
    task_id: str,
    evidence: str,
    profile_skills: list[dict] | None = None,
) -> dict:
    """登记任务完成并给出一份**不落盘**的升级预览。

    委托 :func:`agents.growth_loop.process_task_completion`，签名逐字对应。
    返回体里 ``completion_status`` 用于映射 HTTP 状态码：

    - ``completed`` / ``already_completed`` / 存储写失败 → 200（用 body 说明真相）
    - ``unknown_task`` → 404
    - ``invalid_task_id`` → 422

    整段调用在 :data:`_STORE_WRITE_LOCK` 临界区内执行：并发提交**不同**任务时
    逐个串行落盘，不会互相覆盖；重复提交**同一**任务仍由 ``mark_completed``
    返回 ``already_completed``，首次证据不被覆盖。
    """
    with _STORE_WRITE_LOCK:
        return process_task_completion(
            task_id,
            evidence=evidence,
            loop_store=stores.loop,
            growth_store=stores.growth,
            profile_skills=profile_skills,
        )


def completion_http_status(result: dict) -> int:
    """把 ``process_task_completion`` 的状态映射成 HTTP 状态码。

    ``completion_failed``（存储损坏/写盘失败）**仍返回 200** —— 接口本身跑通了，
    是业务结果是失败态；tests/test_growth_loop_api.py 明确要求此时
    ``completion_written is False`` 而不是伪装成 5xx 或 200 成功。
    """
    status = result.get("completion_status")
    if status == COMPLETE_UNKNOWN_TASK:
        return 404
    if status == COMPLETE_INVALID_TASK_ID:
        return 422
    return 200


#: :func:`clear_tasks` 的三种结果：已清空 / 需要用户确认 / 存储拒绝。
CLEAR_OK = "cleared"
CLEAR_NEEDS_CONFIRM = "needs_confirmation"
CLEAR_REFUSED = "refused"


def clear_tasks(stores: Stores, drop_pending_events: bool = False) -> dict:
    """清空**当前用户**的任务清单：先备份原文件，再重置成空。只动 ``loop.json``。

    为什么先问一句"未记账成果怎么办"
    --------------------------------
    打卡攒下的成长成果是先躺在 ``loop.json`` 的完成记录里的，要等用户点
    「生成下一轮」才正式进成长历史（见 :func:`agents.growth_loop.pending_growth_events`）。
    直接清空会把这些**还没记账的成果**一起删掉 —— 那是真实进度，不该被一次
    "把界面清干净"顺手冲掉。所以默认拒绝，只有前端带着明确确认才丢。

    返回 ``{status, rounds_removed, tasks_removed, backup, pending_events, warning}``；
    ``backup`` 是备份文件名，用户随时可以照着它把清单还原。
    """
    pending = pending_growth_events(loop_store=stores.loop, growth_store=stores.growth)
    events = pending.get("events") or []

    if events and not drop_pending_events:
        return {
            "status": CLEAR_NEEDS_CONFIRM,
            "rounds_removed": 0,
            "tasks_removed": 0,
            "backup": None,
            "pending_events": len(events),
            "warning": "有成果还没进成长历史，清空会一起丢掉，需要明确确认",
        }

    with _STORE_WRITE_LOCK:
        result = stores.loop.clear()

    status = result.get("status")
    return {
        "status": CLEAR_OK if status == "written" else CLEAR_REFUSED,
        "rounds_removed": result.get("rounds_removed", 0),
        "tasks_removed": result.get("tasks_removed", 0),
        "backup": result.get("backup"),
        "pending_events": len(events) if drop_pending_events else 0,
        "warning": result.get("warning"),
    }


# ── 手动补录成长成果（打破空系统死锁）────────────────────────────────────
def add_manual_event(
    stores: Stores,
    kind: str,
    title: str,
    skills: list[str] | None,
    evidence: str,
    target_job: str | None = None,
) -> dict:
    """手动补录一条成长成果：写成一个"已完成任务"进 ``loop.json``。

    目的
    ----
    新用户空系统时没有任何轮次/任务，也就无法通过任务提交产生待处理成果，
    更无法点「生成下一轮」。本函数让用户可以**直接录入**一条自己学过/做过的
    成果：把它实时写成一个``已完成``的任务挂在 ``loop.json`` 上，随后
    ``pending_growth_events`` 就能把它重建为待处理成果，从而打破死锁。

    实现方式
    --------
    复用 ``LoopStore.append_round`` 新开一轮（只含这一条任务），再
    ``LoopStore.mark_completed`` 把它标成完成并写入证据 —— 与正常任务完成
    走的是同一套落盘路径，之后升级判定、去重逻辑全部照常。

    ``target_job`` 缺省时沿用最近一轮的 ``target_job``（都拿不到则为空字符串）。

    在 :data:`_STORE_WRITE_LOCK` 临界区内执行：append + complete 是两段
    独立的读—改—写，必须串行，否则并发请求会互相覆盖。
    """
    if kind not in (KIND_LEARNING, KIND_PROJECT):
        return {"added": False, "reason": f"未知成果类型：{kind!r}（可选 {KIND_LEARNING}/{KIND_PROJECT}）"}

    title = (title or "").strip()
    if not title:
        return {"added": False, "reason": "成果标题不能为空"}
    if not (evidence or "").strip():
        return {"added": False, "reason": "成果证据不能为空"}
    skills = [str(s).strip() for s in (skills or []) if str(s or "").strip()]

    target = (target_job or "").strip()
    if not target:
        latest = stores.loop.latest_round() or {}
        target = str(latest.get("target_job") or "")

    # 按类型构造只含这一条任务的计划：learning 用 topic/covers，project 用 name/covers_gaps
    if kind == KIND_LEARNING:
        learning_plan = [{"topic": title, "covers": skills}]
        project_plan = []
    else:
        learning_plan = []
        project_plan = [{"name": title, "covers_gaps": skills}]

    with _STORE_WRITE_LOCK:
        appended = stores.loop.append_round(target, learning_plan, project_plan)
        if appended.get("status") != WRITE_OK:
            return {
                "added": False,
                "reason": appended.get("warning") or "未能写入任务记录",
                "store_status": appended.get("status"),
            }
        tasks = appended.get("tasks") or []
        if not tasks:
            return {"added": False, "reason": "任务创建后未返回任务条目"}
        task = tasks[0]
        done = stores.loop.mark_completed(task["task_id"], evidence=evidence)
        if done.get("status") != COMPLETE_OK:
            return {
                "added": False,
                "reason": done.get("warning") or "任务标完成失败",
                "task_id": task["task_id"],
            }

    return {
        "added": True,
        "round": appended.get("round"),
        "task_id": task["task_id"],
        "task": jsonable(task),
    }


# ── 分析并保存第一轮任务（根治冷启动死锁）────────────────────────────────
def run_analyze_and_save(stores: Stores, payload) -> dict:
    """跑一次分析，并把产出的学习/项目计划存成第一轮任务。

    背景
    ----
    「岗位分析」原本只读：出一份诊断报告，但不落任何任务。新用户因此永远
    拿不到第一轮任务，形成"分析完还是空的"死锁。本函数让分析**顺手把计划
    存进 loop.json** —— 第一次分析即得到第 1 轮任务，冷启动不再需要手动补录。

    注意
    ----
    这里不写 ``growth.json``（成长历史仍只由「生成下一轮」的 ``growth_node``
    写），只是把分析产出的**学习计划 / 项目计划**落成任务轮次。若已存在轮次
    （比如之前生成过下一轮），则**不**重复追加，避免污染既有轮次 —— 返回
    ``round_created=false`` 并如实告知。

    返回 ``{ok, round_created, round_no, target_job, learning_plan, project_plan,
    analysis (只读分析结果), warning}``。

    分析基线是**当前用户**的 ``stores.growth``（见 ``backend.analyze.run_workflow``
    的 ``baseline_store``）—— 隔离复制看到的历史与这位用户真实一致，而不是
    数据根目录下的旧全局文件。
    """
    from backend.analyze import run_workflow

    loop = stores.loop
    if loop.latest_round() is not None:
        # 已有轮次：保持只读分析语义，不重复建轮次
        analysis = run_workflow(payload, baseline_store=stores.growth)
        return {
            "ok": True,
            "round_created": False,
            "round_no": None,
            "target_job": getattr(payload, "target_job", ""),
            "learning_plan": analysis.get("learning_plan") or [],
            "project_plan": analysis.get("project_plan") or [],
            "analysis": analysis,
            "warning": "已存在轮次，本次分析未重复创建任务（任务已在「学习与项目」页）。",
        }

    analysis = run_workflow(payload, baseline_store=stores.growth)
    learning_plan = list(analysis.get("learning_plan") or [])
    project_plan = list(analysis.get("project_plan") or [])

    target = str(getattr(payload, "target_job", "") or "").strip()
    round_created = False
    round_no = None
    warning = None

    if learning_plan or project_plan:
        with _STORE_WRITE_LOCK:
            # 锁内**重读**再决定：上面那几分钟推理里，别的写入方可能已经建了轮次
            # （用户同时提交手动补录、或另一条分析恰好落盘）。早退分支用的
            # latest_round 是推理**之前**的快照，不重读就会多建一轮重复任务。
            if loop.latest_round() is not None:
                warning = "分析期间已存在轮次，本次未重复创建任务（任务已在「学习与项目」页）。"
            else:
                written = loop.append_round(target, learning_plan, project_plan)
                if written.get("status") == WRITE_OK:
                    round_created = True
                    round_no = written.get("round")
                else:
                    warning = written.get("warning") or "计划未能保存"
    else:
        warning = "本次分析没有生成学习/项目计划，未创建任务轮次。"

    return {
        "ok": True,
        "round_created": round_created,
        "round_no": round_no,
        "target_job": target,
        "learning_plan": learning_plan,
        "project_plan": project_plan,
        "analysis": analysis,
        "warning": warning,
    }


# ── 待处理成长成果（纯只读）──────────────────────────────────────────────
def list_pending(stores: Stores) -> dict:
    """列出"已完成、但还没由 ``growth_node`` 处理过"的成果。**不写任何文件。**"""
    return jsonable(
        pending_growth_events(loop_store=stores.loop, growth_store=stores.growth)
    )


# ── 下一轮成长规划（唯一允许写成长历史的入口）────────────────────────────
def _run_next_round(
    stores: Stores,
    user_profile: dict | None = None,
    target_job: str | None = None,
    jd_text: str | None = None,
) -> dict:
    """用最新能力与最新缺口生成下一轮计划，并**正式写入成长历史**。

    流程（与 ``main.py --loop`` 的菜单 [2] 同一条业务路径）::

        pending_growth_events 重建待办
          → 空：直接返回，**不跑模型、不建轮次**（不伪造成长）
          → 非空：把待办当 growth_events 重跑工作流
                   growth_node 走正式路径写 runs/growth.json 并升级能力
                   → 用新计划写一轮 runs/loop.json

    返回字段与 tests/test_growth_next_round.py 逐字段对应：
    ``ok`` / ``round_created`` / ``round_no`` / ``history_written`` /
    ``history_write_status`` / ``growth_outcome`` / ``growth_upgraded`` / ``warning``。

    ``user_profile`` 缺省时退化为空画像 —— ``profile_node`` 会明确报错，
    该次 run 被 TaskManager 标成 failed，**不会伪造出一轮计划**。
    """
    loop = stores.loop
    growth = stores.growth

    restored = pending_growth_events(loop_store=loop, growth_store=growth)
    events = list(restored.get("events") or [])
    warnings = [str(item) for item in (restored.get("warnings") or [])]

    latest = loop.latest_round() or {}
    resolved_target = str(target_job or latest.get("target_job") or "").strip()

    # 没有待办成果：本轮不改变任何能力，也就没有必要跑模型或新建轮次。
    if not events:
        return {
            "ok": True,
            "round_created": False,
            "round_no": None,
            "history_written": False,
            "history_write_status": None,
            "growth_outcome": "no_events",
            "growth_upgraded": False,
            "events_handed_over": 0,
            "warning": _NO_EVENTS_WARNING,
            "warnings": warnings,
        }

    state = {
        "user_profile": dict(user_profile or {}),
        "target_job": resolved_target,
        "growth_events": events,
    }
    # 下一轮沿用上一轮那份招聘要求原文（由前端带回来）：不传时退回内置知识库，
    # 与既有行为逐字一致。
    pasted = str(jd_text or "").strip()
    if pasted:
        state["jd_text"] = pasted

    # 关键：把工作流内部的 growth_node 指向**注入的** store，
    # 否则它会写默认 runs/，注入就形同虚设。
    with use_growth_store(growth):
        result = workflow.invoke(state)

    diff = result.get("growth_diff") or {}
    history_written = bool(diff.get("history_written"))
    history_write_status = diff.get("history_write_status")
    growth_outcome = diff.get("outcome")
    growth_upgraded = bool(result.get("skill_updates"))

    learning_plan = list(result.get("learning_plan") or [])
    project_plan = list(result.get("project_plan") or [])

    round_created = False
    round_no = None
    warning = None

    if not learning_plan and not project_plan:
        warning = "本轮没有生成任何学习/项目计划，未创建轮次（不记录空轮次）"
    else:
        # 锁只包住落盘这一段（毫秒级），**不含**上面 workflow.invoke 的几分钟推理 ——
        # 否则一次「生成下一轮」会把同时提交的任务完成整整堵死几分钟。
        with _STORE_WRITE_LOCK:
            written = loop.append_round(resolved_target, learning_plan, project_plan)
        if written.get("status") == WRITE_OK:
            round_created = True
            round_no = written.get("round")
        else:
            # 部分成功要如实说：成长历史可能已经写进去了，只有轮次没存下来。
            head = "成长历史已写入，但本轮计划未能保存（部分成功）" if history_written \
                else "本轮计划未能保存，成长历史也未写入"
            warning = f"{head}（{written.get('status')}）：{written.get('warning')}"

    return {
        "ok": True,
        "round_created": round_created,
        "round_no": round_no,
        "history_written": history_written,
        "history_write_status": history_write_status,
        "growth_outcome": growth_outcome,
        "growth_upgraded": growth_upgraded,
        "events_handed_over": len(events),
        "target_job": resolved_target,
        "user_skills": result.get("user_skills") or [],
        "skill_updates": result.get("skill_updates") or [],
        "growth_diff": diff,
        "learning_plan": learning_plan,
        "project_plan": project_plan,
        "warning": warning,
        "warnings": warnings,
    }


def run_next_round(stores: Stores, user_profile=None, target_job=None, jd_text=None) -> dict:
    """``_run_next_round`` 的可序列化包装（HTTP 层用这个）。"""
    return jsonable(
        _run_next_round(stores, user_profile=user_profile, target_job=target_job, jd_text=jd_text)
    )


# ── 只读查询 ────────────────────────────────────────────────────────────
def list_tasks(
    stores: Stores,
    round_no: int | None = None,
    status: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict:
    """查询轮次与任务清单。**只读。**

    ``status`` 非法时抛 ``ValueError``（由 app 层转成 422），
    不静默返回空列表 —— 那会让"参数写错"看起来像"没有任务"。

    ``limit`` / ``offset`` 只对返回的 ``tasks`` 数组开窗；``rounds`` 与
    ``summary`` 永远是**全量口径**，另附 ``pagination`` 块说明窗口位置。
    默认 ``limit=500`` —— 正常使用远用不满，不传参数的老前端行为不变。
    """
    loaded = stores.loop.load()
    try:
        tasks = stores.loop.tasks(round_no=round_no, status=status, data=loaded.data)
    except LoopStoreError as exc:
        raise ValueError(str(exc)) from exc

    total = len(tasks)
    window = tasks[offset:offset + limit] if (offset or limit) else tasks

    rounds = []
    for entry in stores.loop.rounds(loaded.data):
        items = entry.get("tasks") or []
        rounds.append({
            "round": entry.get("round"),
            "target_job": entry.get("target_job"),
            "created_at": entry.get("created_at"),
            "task_count": len(items),
            "completed_count": sum(1 for t in items if t.get("status") == TASK_COMPLETED),
        })

    latest = stores.loop.latest_round(loaded.data)
    return jsonable({
        "store_status": loaded.status,
        "writable": loaded.writable,
        "warning": loaded.warning,
        "rounds": rounds,
        "latest_round": latest,
        "tasks": window,
        "pagination": {"limit": limit, "offset": offset, "returned": len(window), "total": total},
        "summary": {
            "total": total,
            "completed": sum(1 for t in tasks if t.get("status") == TASK_COMPLETED),
            "pending": sum(1 for t in tasks if t.get("status") == TASK_PENDING),
        },
    })


def growth_history(stores: Stores) -> dict:
    """查询真正落盘的成长历史。**只读。**

    存储损坏/不可读时**不掩盖**：原样带出 ``status`` 与 ``warning``，
    并明确说明此时看到的是空表而不是"确实没有成长"。
    """
    loaded = stores.growth.load()
    payload = {
        "status": loaded.status,
        "writable": loaded.writable,
        "warning": loaded.warning,
        "path": str(loaded.path) if loaded.path else None,
        "history": [],
        "latest_skills": [],
        "baseline": None,
        "confirmed_count": 0,
    }
    if not loaded.writable:
        return jsonable(payload)

    history = loaded.data.get("history") or []
    payload["history"] = history
    payload["confirmed_count"] = len(history)
    payload["latest_skills"] = stores.growth.latest_skills(loaded.data)
    payload["baseline"] = loaded.data.get("baseline")
    return jsonable(payload)


# ── 系统状态 ────────────────────────────────────────────────────────────
def _ollama_status(timeout: float = 2.0) -> dict:
    """探测 Ollama 是否可达，并列出已安装模型。不调模型、不生成内容。"""
    url = config.OLLAMA_BASE_URL.rstrip("/") + config.OLLAMA_TAGS_PATH
    info = {
        "ok": False,
        "base_url": config.OLLAMA_BASE_URL,
        "models": [],
        "chat_model": config.CHAT_MODEL,
        "chat_model_ready": False,
        "error": None,
    }
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        names = [str(item.get("name") or "") for item in (payload.get("models") or [])]
        info["models"] = names
        info["ok"] = True
        info["chat_model_ready"] = any(n.split(":")[0] == config.CHAT_MODEL.split(":")[0] for n in names)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _knowledge_status() -> dict:
    """检查技能库 / 项目库能否加载（成长升级与项目推荐都依赖它们）。"""
    result: dict = {}
    try:
        skills = SkillKnowledgeBase(directory=config.SKILLS_DIR)
        # size 是 @property，不是方法
        result["skills"] = {"ok": True, "count": skills.size, "error": None}
    except Exception as exc:  # noqa: BLE001 - 健康检查要如实报告失败原因
        result["skills"] = {"ok": False, "count": 0, "error": f"{type(exc).__name__}: {exc}"}
    try:
        projects = ProjectKnowledgeBase(directory=config.PROJECTS_DIR)
        # projects 是 @property，不是方法
        result["projects"] = {"ok": True, "count": len(projects.projects), "error": None}
    except Exception as exc:  # noqa: BLE001
        result["projects"] = {"ok": False, "count": 0, "error": f"{type(exc).__name__}: {exc}"}
    return result


def health(stores: Stores) -> dict:
    """系统状态：把三类外部依赖的可达性一次说清。**只读。**

    任一依赖不可用只降低整体状态（``degraded``），不视为服务故障 ——
    技能/项目知识库是**增强**而非必需：读不到时分析照常跑，只是学习路线与项目
    推荐会如实告警"无法归一为规范技能名"（见 agents/learning_agent.py）。
    """
    ollama = _ollama_status()
    knowledge = _knowledge_status()

    growth_loaded = stores.growth.load()
    loop_loaded = stores.loop.load()
    stores_info = {
        "growth": {
            "path": str(stores.growth.path),
            "status": growth_loaded.status,
            "writable": growth_loaded.writable,
            "exists": stores.growth.path.exists(),
            "warning": growth_loaded.warning,
        },
        "loop": {
            "path": str(stores.loop.path),
            "status": loop_loaded.status,
            "writable": loop_loaded.writable,
            "exists": stores.loop.path.exists(),
            "rounds": len(loop_loaded.data.get("rounds") or []),
            "warning": loop_loaded.warning,
        },
    }

    healthy = (
        ollama["ok"] and ollama["chat_model_ready"]
        and knowledge["skills"]["ok"] and knowledge["projects"]["ok"]
        and growth_loaded.writable and loop_loaded.writable
    )

    return jsonable({
        "status": "ok" if healthy else "degraded",
        "ollama": ollama,
        "knowledge": knowledge,
        "stores": stores_info,
        "config": {
            "chat_model": config.CHAT_MODEL,
            "runs_dir": str(config.RUNS_DIR),
            "task_workers": config.TASK_WORKERS,
        },
    })


# 让常量在 app 层可用（避免 app 直接依赖 agents.loop_store 的常量名）
COMPLETION_OK = COMPLETE_OK
COMPLETION_ALREADY = COMPLETE_ALREADY
LOOP_STORE_STATUSES = (
    LOOP_STATUS_OK, LOOP_STATUS_EMPTY, LOOP_STATUS_CORRUPT,
    LOOP_STATUS_UNREADABLE, LOOP_STATUS_SCHEMA_MISMATCH,
)