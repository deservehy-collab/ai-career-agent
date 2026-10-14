"""只读分析链路：跑一次完整工作流，**绝不写真实 runs/。**

只读边界是怎么实现的
--------------------
``growth_node`` 是 ``runs/growth.json`` 的**唯一**正式写入方，而它读的是
``agents.growth_agent`` 的**模块级全局 store**。分析接口不该写成长历史，
所以进入工作流前用 :func:`_isolated_growth_store` 把那个全局换成临时目录，
退出时原样还原：

- 分析期间任何"想落盘"的动作都只落在临时目录里，真实 ``runs/`` 逐字节不变；
- 临时目录里会**只读复制**一份现有成长历史，让分析看到的基线与真实一致
  （复制是只读的，不碰原文件）。

这个手法改写的是**进程级全局**，所以它天然要求"同一时刻只有一个分析在跑"——
由 ``backend.jobs.TaskManager`` 的单工作线程保证（见 backend/config.py）。

与测试的对应关系
----------------
- ``workflow`` 必须是**模块级属性**：tests/test_readonly_boundary.py 用
  ``mock.patch.object(analyze_mod.workflow, "invoke", ...)`` 拦截模型调用。
- ``_isolated_growth_store`` 必须在此模块：同上测试 ``from backend.analyze import``。
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Iterator

from agents import growth_agent
from agents.growth_store import GrowthStore
from graph.workflow import build_final_plan, workflow

__all__ = [
    "workflow", "run_workflow", "use_growth_store", "_isolated_growth_store",
    "project_result",
]

#: 透出给前端的 state 字段白名单（其余是内部追踪字段，不对外）。
_PUBLIC_STATE_FIELDS = (
    "user_skills",
    "user_strengths",
    "user_weaknesses",
    "user_skills_before",
    "skill_updates",
    "job_requirements",
    "skill_gaps",
    "learning_plan",
    "project_plan",
    "job_evidence",
    "retrieval_status",
    "retrieval_diagnostics",
)


@contextlib.contextmanager
def use_growth_store(store: GrowthStore) -> Iterator[GrowthStore]:
    """临时把进程级成长 store 换成 ``store``，退出时还原。

    用于「下一轮规划」：工作流内部的 ``growth_node`` 会走正式路径写成长历史，
    必须让它写进**注入的那个** store（正常是 ``runs/``，测试是临时目录），
    否则注入形同虚设。
    """
    previous = growth_agent.get_store()
    growth_agent.set_store(store)
    try:
        yield store
    finally:
        growth_agent.set_store(previous)


@contextlib.contextmanager
def _isolated_growth_store() -> Iterator[GrowthStore]:
    """把一个**临时**的成长 store 设为进程级全局，退出还原。

    与 :func:`use_growth_store` 的区别：这里的目标目录是新建的临时目录，
    调用方碰不到，因此工作流内任何写入都留在临时目录，随退出一起删除。
    """
    previous = growth_agent.get_store()
    tmp_dir = Path(tempfile.mkdtemp(prefix="career-analyze-"))
    try:
        isolated = GrowthStore(directory=tmp_dir)
        # 只读复制现有历史：让分析看到与真实一致的基线，但不改动原文件。
        # 复制失败（权限/占用）不该让分析失败 —— 当作空历史继续，只读性质不受影响。
        with contextlib.suppress(OSError):
            if previous.path.exists():
                shutil.copy2(previous.path, isolated.path)
        growth_agent.set_store(isolated)
        yield isolated
    finally:
        growth_agent.set_store(previous)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def project_result(state: dict) -> dict:
    """把工作流 state 投影成对外结构：白名单字段 + 汇总方案。

    只做投影与序列化，**不改写任何业务字段的取值**。
    """
    payload: dict = {key: state.get(key) for key in _PUBLIC_STATE_FIELDS if key in state}
    payload["growth_diff"] = state.get("growth_diff") or {}
    payload["final_plan"] = build_final_plan(state)
    return jsonable(payload)


def jsonable(payload):
    """JSON 往返，保证响应可安全序列化。

    业务层返回的本来就是 dict/list/str/int/bool，这里走一趟 JSON 只是为了
    **保证**这一点（Chroma 元数据里可能混入 numpy 标量）；``default=str`` 是
    最后一道兜底，只影响类型不是原生 JSON 的个别值，不增删任何字段。
    """
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def run_workflow(payload) -> dict:
    """跑一次只读分析，返回投影后的结果。

    ``payload`` 是 :class:`backend.schemas.AnalyzeRequest`。
    副作用：调用本地 Ollama 做多次推理；**不写任何真实业务数据**。
    """
    with _isolated_growth_store():
        state = workflow.invoke(payload.to_state())
    return project_result(state)
