"""一次性数据迁移：把数据根目录下的单用户旧 store 挪进第一个用户的数据目录。

背景
----
v1.x 的业务数据（数据根目录下的 ``loop.json`` / ``growth.json``）是**全局单份**
的 —— 那时系统没有账号概念。加入注册/登录并按用户隔离数据（见
``backend/deps.create_stores``）之后，旧的根目录文件成了"无主数据"：新代码
只读写 ``users/user_{id}/``，旧文件会被永远晾在那里。

归属规则
--------
迁给**最早注册**的用户（``created_at`` 最小，并列时 id 最小）。这不是拍脑袋：
单用户时代的数据本来就只属于那一位真实使用者；多账号时代才注册的账号不参与
分配，也**绝不**把数据迁给后来者。

安全性
------
- 只在「旧文件存在 且 目标不存在」时复制，**绝不覆盖**任何用户已有数据；
- 复制成功后旧文件改名为 ``<原名>.migrated``（原件保留，不删除，可人工回滚）；
- 幂等：重复调用无副作用（旧文件已改名 / 目标已存在 → 跳过）；
- 所有路径都从 :func:`backend.config.legacy_store_path` 派生、锚定在认证库
  所在目录 —— 测试把 ``AUTH_DB_PATH`` 指到临时目录时，本函数自动变成空操作，
  绝不会碰项目 ``runs/``。

触发时机：应用启动（lifespan）与注册成功后（覆盖"启动时还没有任何账号、
第一个账号注册完成后"的场景）。两处都调没有关系，幂等。
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

from sqlalchemy import select

from backend import config, db

__all__ = ["migrate_legacy_user_data"]

# 串行化迁移本身：启动与注册可能在同一时刻触发，文件操作不并发。
_LOCK = threading.Lock()

#: 单用户时代的两个 store 文件名（与 agents/loop_store.py、growth_store.py 默认名一致）。
_LEGACY_FILES = ("loop.json", "growth.json")


def _first_user_id() -> int | None:
    """最早注册用户的 id；一个账号都还没有时返回 ``None``。"""
    with db.session_for(Path(config.AUTH_DB_PATH)) as session:
        return session.scalar(
            select(db.User.id).order_by(db.User.created_at, db.User.id).limit(1)
        )


def migrate_legacy_user_data() -> dict:
    """把无主的 loop.json / growth.json 迁给最早注册的用户。幂等，不抛出。

    返回一份**如实**的报告（是否迁移、归给了谁、每个文件各自的结果），
    供调用方记日志或排查；失败只体现在报告里，不影响启动。
    """
    report: dict = {
        "migrated": False,
        "claimed_by": None,
        "files": {},
        "reason": None,
    }
    with _LOCK:
        first_user_id = _first_user_id()
        if first_user_id is None:
            report["reason"] = "还没有注册用户，旧数据暂时无主，等第一个账号注册后再迁移"
            return report
        report["claimed_by"] = first_user_id
        target_dir = config.user_data_dir(first_user_id)

        for name in _LEGACY_FILES:
            legacy = config.legacy_store_path(name)
            target = target_dir / name
            if not legacy.exists():
                continue  # 没有这份旧数据，正常情况
            if target.exists():
                report["files"][name] = "目标已存在，跳过（不覆盖用户数据）"
                continue
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy, target)
                legacy.rename(legacy.with_name(f"{name}.migrated"))
            except OSError as exc:
                # Windows 上文件被占用 / 权限问题：如实记录，下次启动再试
                report["files"][name] = f"迁移失败：{type(exc).__name__}: {exc}"
                continue
            report["files"][name] = "已迁移"
            report["migrated"] = True

    return report
