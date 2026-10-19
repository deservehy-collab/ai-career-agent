# AI Career Agent

面向中国大学生与应届生的求职 / 职业成长规划系统：本地 LLM（Ollama）驱动的七节点规划流水线，配 FastAPI 后端与 Vue 3 前端。不使用任何云端 API。

## 架构总览

| 目录 | 职责 |
| --- | --- |
| `backend/` | Web 层适配：路由、认证、后台任务队列、按用户隔离的数据层。**不实现业务规则**，全部委托 agents/ 与 graph/ |
| `agents/` | 业务实现：六个 Agent（profile / growth / retrieval / job / assessment / learning / project）+ 两个 JSON store + RAG 检索器 |
| `graph/` | LangGraph 流水线编排：profile → growth → retrieval → job → assessment → learning → project |
| `knowledge/` | 岗位知识库：skills / projects / jobs 的 YAML 与真实 JD；`index/` 是 Chroma 向量索引（可重建，不入库） |
| `web/` | Vue 3 + Vite 前端 |
| `backend/tests/` | 后端回归测试（**入库**） |
| `tests/` | 全量本地测试（按 .gitignore 约定**不入库**，仅本地） |

## 快速启动

前置：Python 3.11+（含 venv）、Node 18+、本机 [Ollama](https://ollama.com) 并已拉取 `qwen2.5:3b` 与 `nomic-embed-text`。

```bash
# 1. 建索引（首次或知识库变更后）
.venv/Scripts/python.exe scripts/build_index.py

# 2. 起后端（单 worker 是硬要求，见 backend/config.py 的 TASK_WORKERS 说明）
.venv/Scripts/python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1

# 3. 起前端
cd web && npm install && npm run dev   # http://localhost:5173
```

探活：`GET /api/ping`（无鉴权、不探测依赖）；全量体检：登录后 `GET /api/health`。

## 数据布局

```
runs/
├── app.db              # 用户库（SQLite，users 表）
├── jwt_secret.key      # JWT 签名密钥（首次使用时生成；删除等于全员强制登出）
└── users/
    └── user_{id}/      # 每个注册账号一份独立的业务数据
        ├── loop.json   # 任务轮次与完成记录
        └── growth.json # 成长历史与已确认能力
```

单用户时代（v1.x）的 `runs/loop.json`、`runs/growth.json` 会在启动或首个账号注册时由 `backend/migration.py` **一次性迁给最早注册的账号**（幂等；原件改名 `*.migrated` 留档，绝不覆盖已有用户数据）。

## 知识库的角色：增强，不是依赖

`knowledge/` 里的岗位画像、技能/项目模板来自**人工整理的例子**（当前以 AI 应用开发岗为样本），它的定位是给分析**垫事实、提质量**，不是系统运行的前提：

- 检索不到目标岗位的资料时，retrieval 节点降级为空证据，流水线照常走——岗位要求由模型按**该行业**的真实用人标准拆解，逐条标注 `model_supplement`（前端显示"模型补充（无知识库证据）"）；分析结果页的 RAG 面板会如实显示"知识库未提及 / 无可用来源"。
- 五个 Agent 的提示词都按**领域自适应**书写：AI/技术岗沿用原有的分类约束；非信息技术领域（医护、金融、法律、教育等）忽略 AI 分类，按专业知识、实操技能、行业工具、证书资质、软技能拆解。
- 因此系统对**任意专业/岗位**都能做分析；要提升某个岗位的分析质量，往 `knowledge/` 里补该岗位的画像与 JD 再跑 `scripts/build_index.py` 即可——补充资料是"锦上添花"，缺了不会瘫。
- 注意：成长升级的前置门禁依赖 Skill 知识库收录的等级标准，未收录领域的技能会跳过升级（记为 `not_covered`），这是有意的保守行为。

## 多用户模型

- 除 `/api/ping` 与注册/登录外，所有接口要求 Bearer token；`get_current_user` 校验签名后**查库确认账号仍存在**。
- 业务数据按用户隔离：store 目录 `runs/users/user_{id}/`，`GET /api/runs/{run_id}` 只能看到本人提交的后台任务。
- 认证限速（进程内滑动窗口）：登录按 IP+用户名数**失败**次数（成功清零），注册按 IP 数**成功建号**数；阈值见 `backend/config.py`。
- 业务数据的读写互斥靠进程内锁 + 单工作线程（`TASK_WORKERS=1`）保证。

## 已知限制（有意为之或待还的债）

1. **单进程串行**：所有分析/规划任务共享一条单 worker 队列（上限 3，满则 503）。多 worker 会破坏 store 的进程内锁与迁移、隔离逻辑，是硬约束不是配置项。
2. **CLI 与 Web 数据不同源**：`main.py` CLI 仍读写 `runs/` 根目录（单用户工具）；Web 多用户数据在 `runs/users/`。不要用 CLI 改某个账号的数据。
3. **JSON 文件当数据库**：store 层是无锁的读-改-写 + `os.replace` 原子替换。Web 层有服务级写锁保护，但**裸并发调 store**（如 20 线程同时 `mark_completed`）在 Windows 上会触发 `WinError 5` 并丢更新——`tests/test_readonly_boundary.py` 的两个并发用例记录了这一点。
4. **限速是进程内的**：多 worker / 多实例部署时各进程独立计数（当前部署口径就是单 worker，见第 1 条）。
5. **JWT 不可吊销**：登出是前端丢 token；用户删除后其余接口会拒绝（get_current_user 查库），但已签发 token 本身在有效期内仍能通过签名校验。
6. 交互式 API 文档（Swagger）默认关闭——接口全部要求登录，文档页自身没有鉴权入口。

## 测试

```bash
.venv/Scripts/python.exe -m pytest backend/tests -q        # 后端回归（入库的部分）
.venv/Scripts/python.exe -m pytest tests backend/tests -q  # 全量（含本地-only 用例）
```

`tests/` 目录不入库（见 .gitignore 注释），其中 `test_retriever.py` 可能与 `agents/retriever.py` 的当前行为存在漂移。
