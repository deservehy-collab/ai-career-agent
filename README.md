# AI Career Agent

面向中国大学生与应届生的求职 / 职业成长规划系统：本地 LLM（Ollama）驱动的七节点规划流水线，配 FastAPI 后端与 Vue 3 前端。不使用任何云端 API。

## 架构总览

| 目录 | 职责 |
| --- | --- |
| `backend/` | Web 层适配：路由、认证、后台任务队列、按用户隔离的数据层。**不实现业务规则**，全部委托 agents/ 与 graph/ |
| `agents/` | 业务实现：七个 Agent 节点（profile / growth / retrieval / job / assessment / learning / project）+ 两个 JSON store + 技能词表（`skill_dict.py`） |
| `graph/` | LangGraph 流水线编排：profile → growth → retrieval → job → assessment → learning → project |
| `knowledge/` | `skills/`、`projects/` 的 YAML 是技能等级标准与项目模板的来源；`jobs/ai-application-engineer.yaml` 提供技能词表的规范技能名 |
| `web/` | Vue 3 + Vite 前端 |
| `backend/tests/` | 后端回归测试：接口边界、鉴权、并发/生命周期 |
| `tests/` | 业务回归测试：技能名归一、成长记账、学习/项目计划校验（全部入库） |

## 快速启动

前置：Python 3.11+（含 venv）、Node 18+、本机 [Ollama](https://ollama.com) 并已拉取 `qwen2.5:3b`。

```bash
# 1. 起后端（单 worker 是硬要求，见 backend/config.py 的 TASK_WORKERS 说明）
.venv/Scripts/python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1

# 2. 起前端
cd web && npm install && npm run dev   # http://localhost:5173
```

探活：`GET /api/ping`（无鉴权、不探测依赖）；全量体检：登录后 `GET /api/health`。

## 10 分钟复现（评审专用）

从一台没装过本项目的电脑开始，按顺序做下面 7 步。除安装依赖与首次拉模型需要联网，其余全部在本机完成，不需要任何云端 API Key。

> Windows 用 `.venv/Scripts/`；macOS / Linux 换成 `.venv/bin/`。首次先 `python -m venv .venv`。

| 时间 | 做什么 | 命令 / 操作 | 通过标准 |
| --- | --- | --- | --- |
| 0–2 min | 装 Ollama 与模型 | 安装 [Ollama](https://ollama.com) 后执行 `ollama pull qwen2.5:3b`（约 1.9 GB） | `ollama list` 里能看到 `qwen2.5:3b` |
| 2–3.5 min | Python 依赖 | `.venv/Scripts/python.exe -m pip install -r requirements.txt` | 无报错；`python -c "import langgraph, fastapi"` 通过 |
| 3.5–4.5 min | 前端依赖 | `cd web && npm install` | 无 ERESOLVE 报错 |
| 4.5–5.5 min | 起后端 | 另开终端，在仓库根执行 `.venv/Scripts/python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1` | 访问 `http://127.0.0.1:8000/api/ping` 返回 `{"status":"ok",...}` |
| 5.5–6.5 min | 起前端并注册 | `cd web && npm run dev` → 打开 `http://localhost:5173/register` | 注册成功并进入首页 |
| 6.5–9 min | 跑一遍主流程 | 在首页填入目标岗位、粘贴一段真实招聘要求原文 → 开始分析 → 等待结果 | 见下方「这一遍要看什么」 |
| 9–10 min | 跑自动化测试 | `.venv/Scripts/python.exe -m pytest tests backend/tests -q` | `373 passed, 2 xfailed`（约 11 秒） |

**关于登录**：仓库不附带任何用户数据（`runs/` 被 gitignore），所以干净克隆里没有现成账号。登录页的「体验账号」是 `demo / demo1234`——先到注册页用这组用户名密码注册一次，它就会成为可用的演示账号；也可以直接注册自己的账号。

**这一遍要看什么**（对应本项目的核心主张）：

1. **粘了原文**：结果页每条岗位要求都能展开看到它对应的原文句子，标记为「原文依据」；匹配度分母只统计有原文支撑的要求。
2. **不粘原文**：仍然能出分析和计划，但岗位要求整栏标注「模型补充」、**不显示匹配度百分比**，而不是摆一排 0。
3. **任务完成**：学习计划里的任务提交证据后才能标记完成；证据为空会被拒绝。
4. **成长闭环**：完成一条任务后，成长记录里出现对应技能；下一轮计划的缺口会按新能力重算。

一次七节点分析在本机（RTX 4050 6GB + `qwen2.5:3b`）约 1–3 分钟；首次调用还要加载模型，纯 CPU 环境会更久。界面上的数据都是本次操作实时产生的，没有预置演示数据。

### 复现性声明

- **模型与参数固定**：`agents/llm.py` 中 `MODEL_NAME = "qwen2.5:3b"`、`temperature = 0.2`、`num_ctx = 8192`、`num_predict = 2048`。同一份输入在同一模型版本下，**结构与判定规则可复现**（证据回查、匹配度分母、技能归一、成长门禁都是确定性代码），但模型生成的自由文本与个别等级判断可能措辞不同。
- **无云端依赖、无隐藏数据**：不使用任何在线 LLM API；岗位依据只来自「用户粘贴的原文」与「模型推断」两档，仓库内没有预置 JD 语料，也没有向量库。
- **测试可复现**：测试全程 patch 掉模型调用、用临时目录构造 store，不碰项目 `runs/`、不需要 Ollama 在跑，因此结果是确定的秒级回归。`2 xfailed` 是 Windows 上裸并发写 JSON 的已知边界，用例照跑、失败留痕，不算回归（见「已知限制」第 3 条）。
- **运行时数据**：首次启动自动创建 `runs/app.db` 与 `runs/jwt_secret.key`；删除 `runs/` 等于清空所有账号与业务数据，重新注册即可从零复现。

### 可选环境变量

后端**不会自动读取 `.env` 文件**（未引入 python-dotenv），需要时请在启动前 export。两个变量都有默认值，不设置也能完整运行：

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `JWT_SECRET` | 覆盖 JWT 签名密钥，不落 `runs/jwt_secret.key` | 首次使用时随机生成并写入该文件 |
| `OLLAMA_HOST` | 覆盖聊天接口（`/api/chat`）访问的 Ollama 地址 | `http://localhost:11434` |

模板见仓库根目录的 `.env.example`。

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

## 岗位依据只有一个来源：你粘贴的招聘要求原文

retrieval 节点（第 3 节点，现在叫「依据整理」）只做一件事：把用户粘的原文逐句切开。

1. **用户当场粘贴的招聘要求原文**（`AnalyzeRequest.jd_text`，上限 `config.JD_TEXT_MAX_CHARS`）。
   `agents/user_jd.py` 纯文本切句（不调模型），把每句原话投影成与 `job_evidence` **同构**的证据记录，
   下游的编号回查、等级抽取、匹配度分母**全部零改动复用**。
   这条路要求每条要求都能反查到原话：`_attach_evidence` 在原文路径下**只认技能名逐字出现的句子**，
   模型自报的编号一律不收（实测 3B 模型会把"Python"挂到根本没提它的句子上，宁可少认一条也不能认错）。
   `retrieval_status = "user_pasted"`。
2. **没粘原文**——`retrieval_status = "no_source"`，节点交出空证据并写明原因，流水线照常走：
   岗位要求由模型按**该行业**的真实用人标准拆解，逐条标注 `model_supplement`；后端把这一档如实投影成
   `requirement_basis = "model_only"`，前端据此**不给匹配度百分比**、整栏标灰，而不是摆一排 0。

- `requirement_basis` 两档：`user_pasted` / `model_only`（见 `backend/analyze.py`）。
- 五个 Agent 的提示词都按**领域自适应**书写：AI/技术岗沿用原有的分类约束；非信息技术领域（医护、金融、法律、教育等）忽略 AI 分类，按专业知识、实操技能、行业工具、证书资质、软技能拆解。
- 因此系统对**任意专业/岗位**都能做分析；分析质量取决于**你粘的那份原文有多完整**——原文缺一段，对应要求就只能落到"模型补充"。
- **学习路线**的技能归一（`agents/learning_agent.py` 的 `normalize_covers`）不再拿词表当过滤器：词表没收录的名字
  （电气、护理这些岗位天生对不上）退回认本次 `skill_gaps` 的缺口原名记账；模型把 covers 写成缺口编号、或把一个
  复合缺口拆成几个词回报，也都能还原。认不准的一律进 `unmapped_covers` 并如实报告，**不猜**（沾上两个规范技能
  或两个缺口都算认不准）。整条路线一个技能都没关联上时硬失败，不放行一条记不进成长历史的计划。
- ⚠️ 仍未解决：**项目推荐与等级标准**依赖 `knowledge/skills`、`knowledge/projects`（以 AI 岗为样本）。
  非 AI 岗位查不到对应条目，产出质量不如粘贴原文那条路稳；系统只会如实标"未收录"，不会伪造来源。
- 成长升级的前置门禁同样依赖 Skill 知识库：**未收录**的技能按 R5 跳过前置校验、照常升一档（记为 `not_covered`，
  查不到标准不等于不许涨）；**已收录但前置缺失**才拦（`blocked`）；知识库加载失败时门禁根本没执行，标 `unavailable`
  并写明"不代表已通过门禁"。
- 系统里**没有向量检索**：岗位依据只有"你粘的原文"与"模型推断"两档。
  `agents/skill_dict.py` 存的技能词表（规范技能名 + 别名）是查表，不是检索。

## 多用户模型

- 除 `/api/ping` 与注册/登录外，所有接口要求 Bearer token；`get_current_user` 校验签名后**查库确认账号仍存在**。
- 业务数据按用户隔离：store 目录 `runs/users/user_{id}/`，`GET /api/runs/{run_id}` 只能看到本人提交的后台任务。
- 认证限速（进程内滑动窗口）：登录按 IP+用户名数**失败**次数（成功清零），注册按 IP 数**成功建号**数；阈值见 `backend/config.py`。
- 业务数据的读写互斥靠进程内锁 + 单工作线程（`TASK_WORKERS=1`）保证。

## 已知限制（有意为之或待还的债）

1. **单进程串行**：所有分析/规划任务共享一条单 worker 队列（上限 3，满则 503）。多 worker 会破坏 store 的进程内锁与迁移、隔离逻辑，是硬约束不是配置项。
2. **CLI 与 Web 数据不同源**：`main.py` CLI 仍读写 `runs/` 根目录（单用户工具）；Web 多用户数据在 `runs/users/`。不要用 CLI 改某个账号的数据。
3. **JSON 文件当数据库**：store 层是无锁的读-改-写 + `os.replace` 原子替换。Web 层有服务级写锁保护，但**裸并发调 store**（如 20 线程同时 `mark_completed`）在 Windows 上会触发 `WinError 5` 并丢更新——`tests/test_readonly_boundary.py` 的两个并发用例记录了这一点（在 Windows 上被标为"预期失败"：用例照跑、失败照留痕，但不算回归）。
4. **限速是进程内的**：多 worker / 多实例部署时各进程独立计数（当前部署口径就是单 worker，见第 1 条）。
5. **JWT 不可吊销**：登出是前端丢 token；用户删除后其余接口会拒绝（get_current_user 查库），但已签发 token 本身在有效期内仍能通过签名校验。
6. 交互式 API 文档（Swagger）默认关闭——接口全部要求登录，文档页自身没有鉴权入口。

## 测试

```bash
.venv/Scripts/python.exe -m pytest backend/tests -q        # 后端回归
.venv/Scripts/python.exe -m pytest tests backend/tests -q  # 全量
```

- **全程不调 Ollama、不碰项目 `runs/`**：模型调用一律 patch 掉消费方模块上的 `structured_invoke`，
  store 用 `tempfile` 临时目录构造，鉴权在 `tests/conftest.py` 的收集阶段就被覆盖成固定测试用户。
  所以整套跑完是秒级，也不需要本机起着模型。
- 前端没有单测；`cd web && npm run build` 是唯一的静态门禁。
- `tests/` 与 `backend/tests/` 都在库里（`.gitignore` 里记了为什么曾经排除、后来为什么改掉）。
