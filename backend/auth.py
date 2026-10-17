"""认证：注册 / 登录 / JWT 签发与校验 / get_current_user 依赖。

安全口径
--------
- 密码用 PBKDF2-HMAC-SHA256（24 万轮 + 随机盐）哈希后入库，**不存明文**；
  校验走 ``hmac.compare_digest``，避免按字节短路比较带来的计时侧信道。
- JWT 密钥优先取环境变量 ``JWT_SECRET``；没有就在首次使用时生成 32 字节随机
  密钥并持久化到 ``runs/jwt_secret.key`` —— 不硬编码任何默认密钥。
- 登录失败统一回"用户名或密码错误"，不区分"用户不存在"，避免账号枚举。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import config
from backend.db import User, get_session

__all__ = [
    "router", "get_current_user", "hash_password", "verify_password",
    "create_token", "decode_token", "Credentials",
]

# ── 密码哈希 ────────────────────────────────────────────────────────────
_PBKDF2_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ── JWT ────────────────────────────────────────────────────────────────
_secret_cache: str | None = None


def _jwt_secret() -> str:
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    env_secret = os.environ.get("JWT_SECRET")
    if env_secret:
        _secret_cache = env_secret
        return _secret_cache
    path = Path(config.JWT_SECRET_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _secret_cache = path.read_text(encoding="utf-8").strip()
    else:
        _secret_cache = secrets.token_hex(32)
        path.write_text(_secret_cache, encoding="utf-8")
    return _secret_cache


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "iat": now,
        "exp": now + timedelta(hours=config.JWT_TTL_HOURS),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证无效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


# ── get_current_user 依赖 ──────────────────────────────────────────────
bearer_scheme = HTTPBearer(auto_error=False)

Credentials = HTTPAuthorizationCredentials


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """校验请求头里的 Bearer token，返回 {id, username}。

    测试通过 ``app.dependency_overrides[get_current_user]`` 绕过真实鉴权
    （见 tests/conftest.py），所以路由里必须写 ``Depends(get_current_user)``。
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录：请先登录后再访问该功能",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    return {"id": int(payload["sub"]), "username": payload["username"]}


# ── 请求模型与校验 ──────────────────────────────────────────────────────
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]+$")


def _validate_username(value: str) -> str:
    value = value.strip()
    if not (config.USERNAME_MIN_LENGTH <= len(value) <= config.USERNAME_MAX_LENGTH):
        raise ValueError(
            f"用户名长度需在 {config.USERNAME_MIN_LENGTH}~{config.USERNAME_MAX_LENGTH} 个字符之间"
        )
    if not _USERNAME_RE.match(value):
        raise ValueError("用户名只能包含中英文、数字与下划线")
    return value


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, description="用户名：中英文/数字/下划线")
    password: str = Field(min_length=1, description="密码：至少 6 位")

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str) -> str:
        return _validate_username(value)

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if len(value) < config.PASSWORD_MIN_LENGTH:
            raise ValueError(f"密码至少 {config.PASSWORD_MIN_LENGTH} 位")
        if len(value) > 128:
            raise ValueError("密码过长（最多 128 位）")
        return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("username")
    @classmethod
    def check_username(cls, value: str) -> str:
        return value.strip()


# ── 路由 ───────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_response(user: User) -> dict:
    return {"token": create_token(user), "token_type": "Bearer", "user": user.public()}


@router.post("/register", status_code=201, summary="注册")
def register(payload: RegisterRequest, session: Session = Depends(get_session)) -> dict:
    """注册新用户并**直接登录**（返回 token，注册后不用再输一次密码）。"""
    exists = session.scalar(select(User.id).where(User.username == payload.username))
    if exists:
        raise HTTPException(status_code=409, detail=f"用户名 {payload.username} 已被占用")
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail=f"用户名 {payload.username} 已被占用") from None
    session.refresh(user)
    return _auth_response(user)


@router.post("/login", summary="登录")
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> dict:
    user = session.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        # 不区分"用户不存在 / 密码错误"，防账号枚举
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _auth_response(user)


@router.get("/me", summary="当前登录用户")
def me(current: dict = Depends(get_current_user),
       session: Session = Depends(get_session)) -> dict:
    """返回当前 token 对应的用户；用户已被删除时同样报 401。"""
    user = session.get(User, current["id"])
    if user is None:
        raise HTTPException(status_code=401, detail="该账号已不存在，请重新注册或登录")
    return user.public()


@router.post("/logout", summary="退出登录")
def logout(current: dict = Depends(get_current_user)) -> dict:
    """JWT 是无状态 token，退出 = 前端丢弃 token；这里只作确认与界面语义对齐。"""
    return {"ok": True}

