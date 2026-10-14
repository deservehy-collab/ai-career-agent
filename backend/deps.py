"""FastAPI 依赖注入点。

两个函数都是**可被 ``app.dependency_overrides`` 覆盖**的普通函数 ——
tests/test_growth_*_api.py 正是靠覆盖它们把 store 与任务管理器换成临时实例，
从而全程不触碰项目 ``runs/``。所以路由里必须写
``Depends(create_stores)`` / ``Depends(create_task_manager)``，
不能把实例直接抓在模块级变量上。
"""

from __future__ import annotations

from functools import lru_cache

from backend import config
from backend.jobs import TaskManager
from backend.services import Stores

__all__ = ["create_stores", "create_task_manager"]


def create_stores() -> Stores:
    """构造本次请求要用的两个 store。

    两个 store 都**无内存状态**（每次调用重新读盘），因此每个请求新建一份是安全的，
    不需要也不应该做成全局单例 —— 那样反而容易让人误以为它们缓存了数据。
    """
    from agents.growth_store import GrowthStore
    from agents.loop_store import LoopStore

    return Stores(
        growth=GrowthStore(directory=config.RUNS_DIR),
        loop=LoopStore(directory=config.RUNS_DIR),
    )


@lru_cache(maxsize=1)
def _default_task_manager() -> TaskManager:
    """进程级唯一实例。

    必须是单例：``GET /api/runs/{run_id}`` 要能查到 ``POST`` 时提交的那个 run，
    如果每次依赖注入都新建一个 TaskManager，记录就丢了。
    """
    return TaskManager(max_workers=config.TASK_WORKERS)


def create_task_manager() -> TaskManager:
    return _default_task_manager()
