"""FastAPI 应用与路由。

接口总览
--------
======================  ==========================================  ==================
方法 / 路径              作用                                        写盘？
======================  ==========================================  ==================
POST /api/analyze        只读分析（202 + run_id）                     ❌ 只读
GET  /api/runs/{id}      查后台运行状态（排队/成功/失败 + 错误）        ❌ 只读
POST /api/tasks/{id}/complete  登记任务完成 + 升级预览               ✅ 只写 loop.json
GET  /api/growth/pending 待处理成长成果                             ❌ 只读
POST /api/growth/next-round  生成下一轮计划（202 + run_id）          ✅ growth.json + loop.json
GET  /api/growth/history 成长历史                                   ❌ 只读
GET  /api/tasks          轮次 / 任务清单                             ❌ 只读
GET  /api/knowledge/jds  真实 JD 元信息                             ❌ 只读
GET  /api/health         系统状态                                   ❌ 只读
======================  ==========================================  ==================

**唯一允许写成长历史的路径是 POST /api/growth/next-round**（内部经
``growth_node`` 走阶段五正式写入）。任务完成接口只登记完成与证据，
升级只是不落盘的预览 —— 这一点由 tests/test_growth_loop_api.py 强制。

启动（单 worker 是硬要求，见 backend/config.py 的 TASK_WORKERS 说明）::

    .venv/Scripts/python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from agents.loop_store import TASK_STATUSES
from backend import config, services
from backend.analyze import run_workflow
from backend.deps import create_stores, create_task_manager
from backend.jobs import STATUS_QUEUED, TaskManager
from backend.schemas import (
    AnalyzeRequest, CompleteTaskRequest, ManualGrowthEventRequest, NextRoundRequest,
)
from backend.services import Stores

__all__ = ["app"]

app = FastAPI(
    title="AI Career Agent API",
    version="1.0.0",
    description=(
        "AI 大学生成长 / 就业智能规划系统的 Web 接口层。"
        "业务逻辑全部复用现有六阶段实现（agents/ 与 graph/），本层只做适配。"
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 健康检查 ────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"], summary="系统状态")
def get_health(stores: Stores = Depends(create_stores)) -> dict:
    """报告 Ollama / Chroma 索引 / 知识库 / 两个 store 的可达性与可写性。只读。"""
    return services.health(stores)


# ── 分析（只读，异步）─────────────────────────────────────────────────────
@app.post("/api/analyze", status_code=202, tags=["analysis"], summary="发起岗位分析")
def post_analyze(
    payload: AnalyzeRequest,
    manager: TaskManager = Depends(create_task_manager),
) -> dict:
    """把只读分析排进后台队列，立刻返回 ``run_id``。

    一次分析要跑七个节点的本地模型推理，同步等待会让 HTTP 长时间阻塞，
    所以这里只排队；用 ``GET /api/runs/{run_id}`` 查进度与结果。

    **绝不写 runs/** —— 由 ``backend.analyze._isolated_growth_store`` 保证。
    """
    run_id = manager.submit(run_workflow, payload, kind="analyze")
    return {"status": STATUS_QUEUED, "run_id": run_id, "kind": "analyze"}


@app.post("/api/analyze-and-save", status_code=202, tags=["analysis"], summary="分析并保存第一轮任务")
def post_analyze_and_save(
    payload: AnalyzeRequest,
    manager: TaskManager = Depends(create_task_manager),
    stores: Stores = Depends(create_stores),
) -> dict:
    """跑分析，并在**首次**时把产出的学习/项目计划存成第一轮任务。

    这是根治"分析完还是没有任务"冷启动死锁的入口：第一次分析即生成第 1 轮
    任务，翻开「学习与项目」页就能看到。已有轮次时保持只读语义、不重复追加。
    """
    run_id = manager.submit(
        services.run_analyze_and_save, stores, payload, kind="analyze_and_save"
    )
    return {"status": STATUS_QUEUED, "run_id": run_id, "kind": "analyze_and_save"}


@app.get("/api/runs/{run_id}", tags=["system"], summary="查询后台运行状态")
def get_run(run_id: str, manager: TaskManager = Depends(create_task_manager)) -> dict:
    """查一次后台运行的排队 / 成功 / 失败状态、错误信息与结果。

    未知 run_id 返回 404；**失败也返回 200**（接口跑通了，是任务本身失败）。
    """
    snapshot = manager.snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"未知的 run_id：{run_id}")
    return snapshot


# ── 任务完成（只写 loop.json）──────────────────────────────────────────────
@app.post("/api/tasks/{task_id}/complete", tags=["growth"], summary="提交任务完成证据")
def post_task_complete(
    task_id: str,
    payload: CompleteTaskRequest,
    stores: Stores = Depends(create_stores),
) -> dict:
    """登记任务完成与证据，并返回一份**尚未落盘**的技能升级预览。

    证据为空白或超过 5000 字由 :class:`CompleteTaskRequest` 拦成 422。

    重复提交同一任务**幂等**：返回 ``already_completed=true``，
    且第一次的证据不被覆盖（由 LoopStore.mark_completed 保证）。
    """
    result = services.complete_task(
        stores, task_id, payload.evidence, payload.profile_skills
    )
    status_code = services.completion_http_status(result)
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail={
            "task_id": task_id,
            "completion_status": result.get("completion_status"),
            "reason": result.get("reason"),
        })
    return services.jsonable(result)


# ── 待处理成长成果（只读）──────────────────────────────────────────────────
@app.get("/api/growth/pending", tags=["growth"], summary="查询待处理成长成果")
def get_pending(stores: Stores = Depends(create_stores)) -> dict:
    """已完成、但还没交给成长节点的成果。**逐字节只读。**"""
    return services.list_pending(stores)


@app.post("/api/growth/manual-event", tags=["growth"], summary="手动补录一条成长成果")
def post_manual_event(
    payload: ManualGrowthEventRequest,
    stores: Stores = Depends(create_stores),
) -> dict:
    """把用户手动填写的成果写成一条"已完成任务"进 ``loop.json``。

    用于打破"空系统死锁"：尚无任务的全新用户也能直接录入成果，
    让「生成下一轮」有内容可处理。返回 ``added``；失败时带 ``reason``。
    """
    result = services.add_manual_event(
        stores,
        kind=payload.kind,
        title=payload.title,
        skills=payload.skills,
        evidence=payload.evidence,
        target_job=payload.target_job,
    )
    if not result.get("added"):
        raise HTTPException(status_code=422, detail={
            "added": False,
            "reason": result.get("reason"),
        })
    return services.jsonable(result)


# ── 下一轮规划（唯一允许写成长历史）─────────────────────────────────────────
@app.post("/api/growth/next-round", status_code=202, tags=["growth"], summary="生成下一轮成长计划")
def post_next_round(
    payload: NextRoundRequest | None = None,
    manager: TaskManager = Depends(create_task_manager),
    stores: Stores = Depends(create_stores),
) -> dict:
    """把「生成下一轮计划」排进后台队列，立刻返回 ``run_id``。

    这是**唯一**会写 ``runs/growth.json`` 的接口，因此必须在单工作线程里串行执行
    （``TaskManager(max_workers=1)``），否则并发的成长写入会互相覆盖。

    没有待处理成果时不会跑模型，也不会凭空新建轮次。
    """
    profile = payload.user_profile.model_dump() if payload and payload.user_profile else None
    target_job = payload.target_job if payload else None
    run_id = manager.submit(
        services.run_next_round, stores,
        user_profile=profile, target_job=target_job,
        kind="next_round",
    )
    return {"status": STATUS_QUEUED, "run_id": run_id, "kind": "next_round"}


# ── 只读查询 ────────────────────────────────────────────────────────────
@app.get("/api/tasks", tags=["growth"], summary="查询轮次与任务清单")
def get_tasks(
    round_no: int | None = Query(default=None, description="只看某一轮"),
    status: str | None = Query(default=None, description=f"任务状态，可选 {TASK_STATUSES}"),
    stores: Stores = Depends(create_stores),
) -> dict:
    """列出历轮任务与完成情况。只读。"""
    try:
        return services.list_tasks(stores, round_no=round_no, status=status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/growth/history", tags=["growth"], summary="查询成长历史")
def get_growth_history(stores: Stores = Depends(create_stores)) -> dict:
    """返回真正落盘的成长历史与最新确认能力。只读，损坏时如实带出 warning。"""
    return services.growth_history(stores)


@app.get("/api/knowledge/jds", tags=["knowledge"], summary="查询真实 JD 元信息")
def get_jds() -> dict:
    """列出 knowledge/jd 下所有真实 JD 的元信息，供前端选择匹配目标。只读。"""
    return services.list_jds()