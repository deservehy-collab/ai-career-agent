"""后端集中配置：Ollama、模型、CORS、端口与项目路径。

模型名**不在这里另立一套**，而是直接从 Agent 侧导入
（``agents.llm.MODEL_NAME`` / ``agents.retriever.EMBEDDING_MODEL``），
这样前端展示的模型名与真正调用的模型永远不会漂移 —— 本项目不擅自更改
六阶段业务使用的模型。

关于 ``OLLAMA_BASE_URL``
-----------------------
``agents/llm.py`` 里的 ``ChatOllama(model=MODEL_NAME)`` **没有传 base_url**，
因此实际地址由 ollama 客户端的环境变量/默认值决定（默认
``http://localhost:11434``）。后端不修改 Agent 代码，所以这里的常量
**必须与那个默认值一致**；它只用于 ``GET /api/health`` 的连通性探测，
不参与模型调用。若将来要改地址，得改 ``agents/llm.py``（不属本次范围）。
"""

from __future__ import annotations

from pathlib import Path

from agents.llm import MODEL_NAME as CHAT_MODEL
from agents.retriever import EMBEDDING_MODEL

__all__ = [
    "REPO_ROOT", "RUNS_DIR", "KNOWLEDGE_DIR", "CHROMA_INDEX_DIR",
    "SKILLS_DIR", "PROJECTS_DIR",
    "CHAT_MODEL", "EMBEDDING_MODEL", "OLLAMA_BASE_URL", "OLLAMA_TAGS_PATH",
    "HOST", "PORT", "CORS_ORIGINS", "EVIDENCE_MAX_LENGTH", "TASK_WORKERS",
    "TASK_RECORD_CAP", "TASK_QUEUE_CAP",
    "AUTH_DB_PATH", "JWT_SECRET_PATH", "JWT_ALGORITHM", "JWT_TTL_HOURS",
    "USERNAME_MIN_LENGTH", "USERNAME_MAX_LENGTH", "PASSWORD_MIN_LENGTH",
]

# ── 路径 ────────────────────────────────────────────────────────────────
# 与 agents/*_store.py 同口径：以本文件位置反推仓库根，**与 cwd 无关**。
REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
CHROMA_INDEX_DIR = KNOWLEDGE_DIR / "index"
SKILLS_DIR = KNOWLEDGE_DIR / "skills"
PROJECTS_DIR = KNOWLEDGE_DIR / "projects"

# ── 模型（从 Agent 侧导入，见模块 docstring）─────────────────────────────
# CHAT_MODEL / EMBEDDING_MODEL 由上方 import 提供。

# ── Ollama ─────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_TAGS_PATH = "/api/tags"

# ── 服务 ────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8000

# Vite 开发服务器默认端口（前端重建后用这个地址联调）
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# ── 业务约束 ────────────────────────────────────────────────────────────
# 任务证据的字符上限：空白拒绝、超长拒绝，由 schemas.CompleteTaskRequest 执行。
EVIDENCE_MAX_LENGTH = 5000

# 后台任务的并发上限。**必须是 1**：runs/growth.json 与 runs/loop.json 的
# 读-改-写只在进程内串行安全（见 tests/test_readonly_boundary.py），
# 且分析链路的成长存储隔离会临时改写进程级全局 store。
TASK_WORKERS = 1

# 后台运行记录的保留上限。记录只存在内存里（进程级单例），原先没有任何上限，
# 一次分析产出的完整 state 会一直挂在 ``TaskManager._records`` 上。
# 淘汰只发生在**已终态**的最旧记录上（queued / running 永不淘汰），
# 被淘汰的 run_id 之后查询返回 404。
TASK_RECORD_CAP = 200

# 同时"在跑或排队"的任务数上限。单 worker + 一次七节点推理要几分钟，
# 没有上限时双击"开始分析"会排出一串重复任务，白等也白算。
# 超出后 ``POST`` 直接 503（不是 202），前端按错误提示处理。
TASK_QUEUE_CAP = 3

# ── 认证（登录 / 用户数据库）─────────────────────────────────────────────
# SQLite 与 JWT 密钥都放在 runs/ 下：那里本就是"可再生成的运行数据"目录，
# 删掉库文件最多是重新注册，不会伤到 knowledge/ 与业务代码。
AUTH_DB_PATH = RUNS_DIR / "app.db"
JWT_SECRET_PATH = RUNS_DIR / "jwt_secret.key"
JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = 24

USERNAME_MIN_LENGTH = 2
USERNAME_MAX_LENGTH = 32
PASSWORD_MIN_LENGTH = 6
