---
source_id: jd_hundsun_001
company_slug: hundsun
origin: jd_raw
source: 牛客网（nowcoder.com）
url: https://www.nowcoder.com/jobs/detail/456959?urlSource=sitemap
collected_at: 2026-10-09
job_name: AI应用开发工程师（J10355）
job_id: ai_application_engineer
company: 恒生电子股份有限公司
city: 杭州
salary: 15-30K * 14薪
education: 本科及以上
publish_window: 2026-07-29 ~ 2029-07-29（页面「投递时间」区间）
record_created_at: 2026-07-29 10:01:46
record_deliver_end: 2029-07-29 10:01:47
status: "待核实"
status_evidence:
  指向已结束:
    - "投递按钮渲染为「已结束」，按钮为不可点击的信息态样式（el-button--info）"
    - "内嵌字段 store.jobDetail.detail.status = 1（枚举含义未在页面任何位置说明，无法解读）"
  指向未结束:
    - "内嵌字段 detail.deliverEnd = 2029-07-29 10:01:47，晚于采集日 2026-10-09"
    - "页面「投递时间」显示 2026年7月29日-2029年7月29日"
  说明: >
    两方信号互相矛盾，本文档不作任何招聘状态判定，如实记为「待核实」。
    可核验的观测事实（不构成结论）：createTime 与 deliverEnd 恰好相隔 3 年零 1 秒；
    记录的 updateTime 为 2026-10-09 09:11:19（采集当日）。成因未知。
mentioned_skills:
  - Python
  - Java
  - 大模型核心概念（模型选型、上下文理解、token 机制）
  - LLM API 调用与调试（通义千问、文心一言等）
  - Prompt 工程
  - RAG 检索增强生成
  - 数据结构与算法
  - 计算机网络
  - 操作系统
  - Linux
  - Git
  - SQL
  - Flask / FastAPI / SpringBoot（优先）
  - Hugging Face / LangChain（优先）
  - PyTorch / TensorFlow 基础（优先）
  - 模型部署与优化
source_notes: |
  访问情况：curl 抓取成功，HTTP 200，页面内容完整可见，无登录墙或验证码拦截。
  采集时间：2026-10-09。
  发布主体：牛客网是第三方招聘平台，本页面由牛客网校招策划账号发布，
  **不是恒生电子官网原始公告**。
  届别：2027 届。
  章节结构：本 JD 用「岗位职责」+「岗位要求」两个章节，没有「加分项」章节。
  "优先"字样出现 3 次，均为内嵌在「岗位要求」条目中的修饰，故本 JD 的证据
  只会出现 context: responsibility / qualification，不会出现 bonus_section。
  【状态冲突 — 待人工核实】见 status_evidence。展示时必须提示"招聘状态待核实"。
  【英语要求】本 JD 的 9 条岗位要求中无任何英语条目。
  英语要求只出自 jd_zhongzhi_001，不得错误归属本来源。
  未采信信息：页面未给出独立的「发布时间」字段；本文档以 record_created_at 记录
  记录创建时间，**不得将其等同于招聘发布时间**。
  本摘要为人工提炼，非招聘原文；关键表述保留原文用词。
---

## 岗位概要（摘要，非原文）

**公司**：恒生电子股份有限公司（金融科技，已上市，杭州）
**岗位**：AI应用开发工程师（J10355），2027 届校招
**地点 / 薪资 / 学历**：杭州 / 15-30K × 14 薪 / 本科及以上
**状态**：⚠️ **待核实** —— 展示时必须提示"招聘状态待核实"

**工作内容方向**：内部研发提效场景的 AI 应用探索与落地，工具研发与迭代。

**岗位要求（「岗位要求」章节，共 9 条）**

| # | 要点 | 页面标注 |
|---|---|---|
| 1 | 本科及以上学历，计算机/软件工程/人工智能等专业 | 明确要求 |
| 2 | 熟练掌握 Python 或 Java 任一；有大模型工具开发、AI应用落地经验（如RAG系统、智能助手）者优先 | 前半明确 / 后半**优先** |
| 3 | 数据结构、算法、计算机网络、操作系统基础 | 明确要求 |
| 4 | Linux、Git 版本控制、SQL 基本操作 | 明确要求 |
| 5 | Python（Flask/FastAPI）或 Java（SpringBoot）后端框架 | **优先** |
| 6 | 大模型核心概念（模型选型、上下文理解、token 机制） | 明确要求 |
| 7 | 主流 LLM API（通义千问、文心一言等）调用与调试经验 | 明确要求 |
| 8 | Prompt 工程技巧、RAG 检索增强生成核心流程 | 明确要求 |
| 9 | Hugging Face、LangChain 等工具；PyTorch/TensorFlow 基础 | **优先** |

**岗位职责（「岗位职责」章节，共 3 条）**

1. 负责 AI 应用的探索与验证，聚焦内部研发提效场景落地，推进相关提效工具的研发与迭代。
2. 使用 Python 完成大模型调用、数据处理及接口封装。
3. 参与大模型能力在内部提效场景的工程化落地，协助完成模型部署、优化及技术文档编写。

**未提及**：英语要求、Docker、Agent、SQL 以外的数据库要求、云服务。
