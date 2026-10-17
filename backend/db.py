"""SQLite 数据库层：引擎、Session 与用户表。

设计约束
--------
- 引擎**按数据库路径惰性缓存**：``create_engine`` 本身不碰磁盘，文件与建表
  都推迟到第一次真正连接时（``init_db``），因此测试只要把
  ``config.AUTH_DB_PATH`` 指到临时目录就能完全隔离，不需要重置模块状态。
- SQLite + FastAPI 同步端点跑在线程池里（每请求可能换线程），所以连接必须
  ``check_same_thread=False``；本项目后端是**单 worker 硬要求**（见
  backend/config.py 的 TASK_WORKERS），单进程内共享一个连接池是安全的。
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend import config

__all__ = ["Base", "User", "get_session", "init_db", "session_for"]


class Base(DeclarativeBase):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    def public(self) -> dict:
        """返回给前端的用户信息：**永远不包含**密码哈希。"""
        return {
            "id": self.id,
            "username": self.username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


_cache: dict[Path, sessionmaker] = {}
_cache_lock = threading.Lock()


def _factory(db_path: Path) -> sessionmaker:
    with _cache_lock:
        if db_path not in _cache:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                f"sqlite:///{db_path}",
                connect_args={"check_same_thread": False},
            )
            Base.metadata.create_all(engine)
            _cache[db_path] = sessionmaker(bind=engine, expire_on_commit=False)
        return _cache[db_path]


def session_for(db_path: Path) -> Session:
    """针对指定数据库文件开一个 Session（测试用临时库时走这里）。"""
    return _factory(db_path)()


def init_db() -> None:
    """确保数据库文件与表结构就绪（幂等）。"""
    _factory(Path(config.AUTH_DB_PATH))


def get_session():
    """FastAPI 依赖：每请求一个 Session，请求结束自动关闭。"""
    with session_for(Path(config.AUTH_DB_PATH)) as session:
        yield session
