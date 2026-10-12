"""岗位知识库检索模块（RAG Retriever）。

设计要点
--------
1. **只读**：本模块不写入、不重建、不删除任何索引。Chroma 与 Ollama 客户端均为
   惰性创建 —— 导入本模块不会连接任何服务，也不会触碰 `knowledge/index/`。
2. **可测试**：向量后端与技能词表都通过构造函数注入，单元测试可替换为内存假实现，
   因此测试不依赖本地 Ollama 服务。
3. **不使用固定距离阈值**：向量库的 L2 距离只用于排序与诊断，**不用于判定"相关"**。
   四种判定各自有明确的依据：
   - 「有明确证据」＝ 技能精确匹配后，在适用范围内做**全量**记录核对；
   - 「未提及」＝ ① 精确技能在适用范围内全量核对无果，或
     ② 查询中的某个**内容单元**（见 `extract_content_units`）在适用范围的
     全量记录文本中**整个单元**都找不到 —— 判定粒度是单元，所以通用词（如 `AI`）
     的命中不会抵消「量子计算」这类核心主题的完全未命中；
   - 「整体性问题」＝ 查询没有指向任何具体事项（无技能词、无内容单元，或内容词
     横跨多个技能而没有焦点），此时按**技能聚合**回答，而不是把向量 Top-K 当作证据；
   - 「语义检索」＝ 有内容词且能在资料里找到，但没有聚焦到具体技能。
   向量检索 Top-K 未命中，永远不会被当作"该技能不存在"。
4. **不跨公司**：公司过滤在 Chroma metadata 层完成，一家公司的证据不会用于回答
   另一家公司的问题；未提及就是未提及，不用别家数据填补。内容单元核对同样只在
   **适用范围**的文本内进行，因此别家公司有、这家没有的事项仍判为"未提及"。
5. **不靠字面**：技能词表除字面名称外带别名/上位词（`SKILL_ALIASES`），
   使"Agent 开发框架""MCP""容器技术""向量数据库"这类问法能走确定性路径。
   同一张别名表也参与内容单元判定，两处口径一致。
6. **点名了的技能不丢证据**：同一条 JD 原文常常同时是多个技能的证据。检索层会按
   `(source_id, 原文, requirement_type)` 合并这类近重复以避免重复占位，但
   **查询里明确点到的技能受保护**——共享原文不能让任何一个被点名的技能从 evidence
   里消失（被合并方只写进 `also_supports` 不算数）。`required` 与 `bonus`
   等不同性质**不合并**。
7. **样本量写在结果里**：跨公司概览只在当前几份 JD 的样本内成立，
   `diagnostics["sample_scope"]` 与每条 evidence 的 `jd_count` / `companies`
   都会写明样本范围与覆盖公司，不把 3 家公司说成整个行业的共性。

四种状态
--------
- ``matched``       找到符合条件的明确证据
- ``not_mentioned`` 核对了适用范围的**全部**记录，没有找到明确证据
- ``no_source``    没有可用的适用岗位资料（索引缺失 / 该来源无记录）
- ``ambiguous``    查询涉及多家公司，需要用户澄清

``diagnostics["match_kind"]`` 说明命中的是哪条路径：
- ``exact_skill`` 技能精确（或别名）匹配 + 全量核对
- ``vector_only`` 有内容词且能在资料中找到，按语义排序返回
- ``overview``    整体性问题，按技能聚合（跨公司时体现共性）
- ``term_scan``   内容词在资料中完全找不到，判定为 not_mentioned

已知限制
--------
1. `match_kind == "vector_only"` 的相关性**未经技能词校验**，只由语义相似度排序，
   调用方应结合 `diagnostics` 判断是否采信。
2. 内容词核对是"词面"判定：别名词表未覆盖、且原文用词也不同的表达仍可能被判成
   未提及。判定结果与所用词条都写在 `diagnostics` 中，便于人工复核。
3. `overview` 路径按技能的重要性与跨公司覆盖度聚合，不回答"某公司是否要求某技能"
   这类具体问题 —— 那类问题应带公司名与技能名。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

# ── 常量（本模块自带，不新增配置文件）────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent

COLLECTION_NAME = "job_knowledge"
EMBEDDING_MODEL = "nomic-embed-text:latest"
DEFAULT_INDEX_DIR = REPO_ROOT / "knowledge" / "index"
DEFAULT_PROFILE_PATH = REPO_ROOT / "knowledge" / "jobs" / "ai-application-engineer.yaml"

DEFAULT_JOB_ID = "ai_application_engineer"
DEFAULT_TOP_K = 5

STATUS_MATCHED = "matched"
STATUS_NOT_MENTIONED = "not_mentioned"
STATUS_NO_SOURCE = "no_source"
STATUS_AMBIGUOUS = "ambiguous"
STATUSES = (STATUS_MATCHED, STATUS_NOT_MENTIONED, STATUS_NO_SOURCE, STATUS_AMBIGUOUS)

MODE_AUTO = "auto"
MODE_COMPANY = "company_specific"
MODE_FAMILY = "job_family"
MODES = (MODE_AUTO, MODE_COMPANY, MODE_FAMILY)

# 公司别名。每个公司内部按长度降序，保证"较长的公司名优先匹配"。
COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "hundsun": ("恒生电子股份有限公司", "hundsun", "恒生电子", "恒生"),
    "zhongzhi": ("北京众智诚坚科技有限公司", "北京众智诚坚科技", "zhongzhi", "北京众智诚坚", "众智诚坚"),
    "yisiwei": (
        "易思维（杭州）科技有限公司", "易思维(杭州)科技有限公司",
        "易思维（杭州）科技", "易思维(杭州)科技",
        "易思维（杭州）", "易思维(杭州)", "yisiwei", "易思维",
    ),
}

COMPANY_NAMES: dict[str, str] = {
    "hundsun": "恒生电子股份有限公司",
    "zhongzhi": "北京众智诚坚科技有限公司",
    "yisiwei": "易思维（杭州）科技有限公司",
}

# ── 技能别名 / 上位词 ───────────────────────────────────────────────────
# 键必须是岗位画像 YAML 中真实存在的技能名（`SkillVocabulary` 会再校验一次，
# 目标技能不在词表内时该别名直接失效，避免把查询引向不存在的技能）。
# 别名只解决"问法与原文用词不同"的问题，不做同义词联想以外的泛化：
# 例如「框架」单独出现**不**触发任何技能，只有「开发框架」「智能体框架」这类
# 明确指向 Agent/RAG 开发框架的说法才映射到 LangChain / LangGraph。
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    # 注意：这里**只收**明确指向 Agent/RAG 开发框架的说法。
    # 裸词「开发框架」会把"后端开发框架"（=Flask/SpringBoot，属后端 API 开发）错误地
    # 引到这里，因此不收；后端侧的说法收在「后端 API 开发」下。
    "LangChain / LangGraph": (
        "agent 开发框架", "agent开发框架", "agent 框架", "agent框架",
        "智能体框架", "智能体开发框架", "编排框架", "大模型开发框架",
        "大模型开发工具", "lang chain", "lang graph",
    ),
    "Agent Skill / MCP 工具封装": (
        "mcp", "model context protocol", "mcp server", "mcp 工具", "mcp工具",
        "mcp 工具封装", "mcp工具封装", "agent skill",
    ),
    "Agent": ("智能体", "ai agent", "agent 架构"),
    "RAG": ("检索增强生成", "检索增强", "知识库检索"),
    "LLM API": ("大模型 api", "大模型api", "大模型的调用", "模型调用接口"),
    "Prompt Engineering": ("提示词工程", "提示词", "prompt 工程", "prompt工程", "prompt 设计"),
    "Function Calling": ("函数调用", "工具调用"),
    "Embedding": ("向量化", "向量数据库", "向量检索", "向量存储", "文本向量",
                  "embedding 模型", "embedding模型"),
    # 后端侧的上位词：`后端开发` 让"后端开发框架"落在正确地技能上，而不是 LangChain。
    "后端 API 开发": ("后端服务", "后端开发", "服务端开发", "接口开发", "api 开发", "后端框架"),
    "测试与效果评测": ("效果评测", "测试体系", "评测体系", "应用评测"),
    "数据结构与算法": ("算法基础",),
    "Git": ("版本控制",),
    "Linux": ("linux 环境", "linux环境"),
    "SQL": ("数据库操作",),
    "Docker": ("容器化", "容器化部署", "容器技术", "容器环境", "容器"),
}

# ── 内容词抽取所需的词表 ────────────────────────────────────────────────
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#._\-]*")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")

STOPWORDS_EN = frozenset({
    "the", "and", "for", "are", "was", "were", "has", "have", "had", "does", "did",
    "what", "which", "who", "how", "why", "when", "where", "there", "this", "that",
    "these", "those", "any", "all", "some", "can", "could", "would", "should",
    "about", "with", "from", "into", "tell", "give", "show", "list", "explain",
    "please", "need", "needs", "needed", "require", "requires", "required",
    "job", "jobs", "company", "companies", "skill", "skills", "role", "position",
    "must", "may", "not", "you", "your", "it", "its", "is", "be", "or", "of",
    "to", "in", "on", "at", "as", "by", "an", "do", "me", "my", "we", "us", "vs",
})

# 中文停用词：疑问词、泛指词、岗位套话与虚词。只用于**判断有无证据**，
# 不参与排序。处理时按长度降序依次剔除，避免"有没有"被"有"先行拆坏。
STOPWORDS_ZH = (
    # 章节/套话
    "岗位要求", "任职要求", "加分项", "职位描述",
    # 疑问与泛指
    "有没有", "有什么", "有哪些", "什么样", "哪些技能", "什么技能", "是什么",
    "不指定", "指定",
    "什么", "哪些", "哪个", "哪家", "哪种", "怎么", "怎样", "如何", "是否", "能否",
    "可以", "能不能", "一个", "一下", "一点", "这些", "那些", "这个", "那个",
    "本次", "其中", "主要", "具体", "明确", "通常", "一般", "整体", "综合",
    "全部", "所有", "分别", "到底", "究竟", "大概", "多少", "几个", "一样",
    "提到", "说到", "说说", "看看", "介绍", "总结", "汇总", "对比", "比较",
    "分析", "帮我", "列出", "告诉", "说明",
    # 通用名词
    "岗位", "职位", "公司", "企业", "技能", "能力", "要求", "需要", "条件",
    "内容", "方面", "相关", "情况", "职责", "描述", "章节", "原文", "标题",
    "标准", "程度", "水平", "时候",
    # 虚词
    "的", "地", "得", "了", "吗", "呢", "是", "和", "与", "或", "对", "在",
    "时", "都", "就", "也", "还", "把", "被", "从", "为", "以", "及", "之",
    "其", "等", "些", "个",
)
_STOPWORDS_ZH_BY_LEN = tuple(sorted(STOPWORDS_ZH, key=len, reverse=True))

# 中文连词：先把它们换成切分点再抽内容单元，否则"日志和监控"会被并成一个长片段，
# 两侧的真实词条都核不到。只收不会嵌在常用词内部的连词（不收"与/及"——"参与""相似""涉及"里都有）。
_CONJUNCTIONS = ("以及", "或者", "跟", "和", "或")

# 「整体性问题」的**短语**标志：问的是"这个岗位大概要什么"，而不是某个具体事项。
# 这只是三条判据之一（另两条见 `is_overview_query`：没有内容单元 / 内容词横跨多个技能），
# 因此整体性问题不依赖固定短语也能被识别。
OVERVIEW_MARKERS = (
    "要什么", "要求什么", "需要什么", "需具备什么", "哪些技能", "什么技能",
    "有哪些要求", "要求有哪些", "通常要求", "一般要求", "主要要求", "整体要求",
    "总结", "汇总", "概况", "概览", "介绍一下", "介绍下", "到底要", "到底需要",
)

# 命中内容词横跨多少个技能就算"没有指向具体事项"。取值 3：只碰到 1–2 个技能时，
# 问题仍然是有焦点的（按语义检索回答更合适）；横跨 3 个以上说明问题在问整个岗位。
OVERVIEW_SKILL_SPREAD = 3

# requirement_type 的强度排序：required 比 preferred 更硬，bonus 最弱。
_RT_RANK = {"required": 0, "preferred": 1, "bonus": 2}

# 判为"未提及"时，向量候选只放进 diagnostics，供人工复核
_NO_EVIDENCE_NOTE = (
    "判定为「未提及」是因为在**适用范围的全部记录**里核对不到查询的核心词，"
    "不是因为向量距离大；向量候选仅列在 diagnostics 中，未作为证据返回，"
    "也未用其他公司或其他技能的内容顶替。"
)


# ── 通用文本工具 ────────────────────────────────────────────────────────
def _contains_term(haystack: str, needle: str) -> bool:
    """ASCII 词按词边界匹配（避免 Git 命中 digit、RAG 命中 storage），中文按子串匹配。"""
    if not needle:
        return False
    if needle.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None
    return needle in haystack


def _strip_stopwords(text: str) -> str:
    """按长度降序剔除中文停用词。"""
    out = text
    for word in _STOPWORDS_ZH_BY_LEN:
        if word in out:
            out = out.replace(word, "")
    return out


@dataclass(frozen=True)
class ContentUnit:
    """查询里的一个「内容单元」：一个 ASCII 词，或一段去掉通用词后的中文片段。

    `probes` 是用于词面核对的探针。整个单元**所有**探针都核不到，才算这个单元
    「完全未命中」—— 这一点很关键：「AI 量子计算经验」里 `ai` 命中、`量子计算经验`
    完全没命中，两者是不同单元，前者不能抵消后者。
    """

    text: str
    probes: tuple[str, ...]
    kind: str  # "ascii" | "han"


def extract_content_units(text: str) -> list[ContentUnit]:
    """把查询拆成「内容单元」，用于判断问题指向的主题在资料里到底有没有。

    步骤：
    1. 去掉公司别名 —— 「恒生电子」这类词只决定检索范围，不构成内容主题；
    2. 按中文连词切开（避免"日志和监控"被并成长片段）；
    3. 抽出 ASCII 词（长度 ≥ 2，排除英文停用词），每个词自成一个单元；
    4. 中文部分剔除疑问词/泛指词/岗位套话，按非中文字符切段，每段一个单元；
       段长 ≤3 时以整段为探针，更长时取 3-gram 与 4-gram。

    用 3-gram 起步而不是 2-gram：2-gram「计算」会命中原文的「计算机网络」，
    使「量子计算」被误判成"资料里有"。这些词只参与"有无证据"的判定，
    **不参与排序，也不是距离阈值**。
    """
    if not text:
        return []

    working = text
    aliases = [a for group in COMPANY_ALIASES.values() for a in group]
    for alias in sorted(aliases, key=len, reverse=True):
        working = re.sub(re.escape(alias), " ", working, flags=re.I)
    for conjunction in _CONJUNCTIONS:
        working = working.replace(conjunction, " ")

    units: list[ContentUnit] = []
    seen: set[tuple[str, str]] = set()

    def add(unit_text: str, probes: list[str], kind: str) -> None:
        key = (unit_text, kind)
        if not unit_text or key in seen:
            return
        seen.add(key)
        units.append(ContentUnit(unit_text, tuple(probes), kind))

    for token in _ASCII_TOKEN_RE.findall(working):
        low = token.lower()
        if len(low) >= 2 and low not in STOPWORDS_EN:
            add(low, [low], "ascii")

    for run in _CJK_RUN_RE.findall(_ASCII_TOKEN_RE.sub(" ", working)):
        for segment in _CJK_RUN_RE.findall(_strip_stopwords(run)):
            if len(segment) < 2:
                continue
            if len(segment) <= 3:
                add(segment, [segment], "han")
                continue
            probes: list[str] = []
            for size in (3, 4):
                for i in range(len(segment) - size + 1):
                    probe = segment[i:i + size]
                    if probe not in probes:
                        probes.append(probe)
            add(segment, probes, "han")
    return units


def extract_content_terms(text: str) -> list[str]:
    """（保留的扁平视图）把所有内容单元的探针拉平成一个列表。"""
    terms: list[str] = []
    for unit in extract_content_units(text):
        for probe in unit.probes:
            if probe not in terms:
                terms.append(probe)
    return terms


def _alias_hit(text: str, alias_words: tuple[str, ...]) -> bool:
    """`text` 是否命中了技能别名/上位词表 —— 让内容词判定与别名表共用同一套词。"""
    low = (text or "").lower()
    return any(_contains_term(low, word) for word in alias_words)


def _record_text(record: dict) -> str:
    """一条记录可用于"词面核对"的全部文本。"""
    return " ".join(
        str(record.get(key) or "") for key in ("skill", "note", "requirement_type", "context")
    ).lower()


def _norm_note(note) -> str:
    """原文归一化：只去空白，不改字，用于判断"是否同一句原文"。"""
    return re.sub(r"\s+", "", str(note or ""))


def is_overview_query(
    text: str,
    units: list[ContentUnit] | None = None,
    matched_skills: set[str] | None = None,
) -> bool:
    """判断是否为"整体性问题"（问这个岗位大概要什么，而非某个具体事项）。

    三条判据，满足其一即可 —— 不再只依赖固定短语：
    1. 出现整体性短语（`OVERVIEW_MARKERS`，如"要什么""哪些技能"）；
    2. 去掉通用词后**没有剩下任何内容单元**（"这个岗位到底要什么"）；
    3. 命中的内容词**横跨 ≥ OVERVIEW_SKILL_SPREAD 个技能**（"要会什么"里
       "应用开发""ai"同时命中 RAG/Agent/Function Calling 等）→ 问题没有焦点。

    判据 3 是从**当前语料**算出来的收敛度，而不是短语匹配，所以换一种问法仍然有效。
    """
    if not text:
        return False
    low = text.lower()
    if any(marker.lower() in low for marker in OVERVIEW_MARKERS):
        return True
    if units is not None and not units:
        return True
    if matched_skills is not None and len(matched_skills) >= OVERVIEW_SKILL_SPREAD:
        return True
    return False


def _candidate_k(top_k: int) -> int:
    """向量检索的取样上限：多取一些，供同源合并与多样性筛选后仍能填满 top_k。"""
    return max(top_k * 4, 20)


def metadata_filter(
    company_slug: str | None, source_ids=None,
) -> dict | None:
    """构造 Chroma metadata filter：公司 + JD 白名单，两者取**交集**。

    ``source_ids`` 用于"只匹配某一份真实 JD"（阶段四）：向量候选必须在数据库侧
    就被限制在该 JD 范围内，而不是取回来之后再过滤 —— 否则同公司的其他 JD 会先
    混进候选、再靠后续环节补救。不传 ``source_ids`` 时行为与阶段二完全一致。
    """
    allowed = sorted({str(s).strip() for s in (source_ids or ()) if str(s).strip()})
    conditions: list[dict] = []
    if company_slug:
        conditions.append({"company_slug": company_slug})
    if allowed:
        conditions.append({"source_id": {"$in": allowed}})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


# ── 公司识别 ────────────────────────────────────────────────────────────
def detect_companies(text: str) -> list[str]:
    """从文本中识别出现的公司 slug，按"最长别名优先"匹配，不重复计入同一公司。"""
    if not text:
        return []
    lowered = text.lower()
    # 全部别名按长度降序，长名称先匹配（如"北京众智诚坚科技"先于"众智"）
    pairs = sorted(
        ((alias, slug) for slug, aliases in COMPANY_ALIASES.items() for alias in aliases),
        key=lambda p: len(p[0]),
        reverse=True,
    )
    found: list[str] = []
    for alias, slug in pairs:
        if alias.lower() in lowered and slug not in found:
            found.append(slug)
    return found


def resolve_company(value: str) -> str | None:
    """把公司名/简称/slug 解析成 slug；无法识别返回 None。"""
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    if text.lower() in COMPANY_ALIASES:
        return text.lower()
    hits = detect_companies(text)
    if len(hits) == 1:
        return hits[0]
    # 完全匹配某个别名（避免 "易" 这类过短子串误判）
    for slug, aliases in COMPANY_ALIASES.items():
        if text in aliases:
            return slug
    return None


# ── 请求 / 结果结构 ─────────────────────────────────────────────────────
@dataclass
class RetrieveRequest:
    """检索请求。"""

    query: str
    company: str | None = None
    job_id: str = DEFAULT_JOB_ID
    top_k: int = DEFAULT_TOP_K
    mode: str = MODE_AUTO
    source_id: str | None = None


@dataclass
class RetrieveResult:
    """检索结果。"""

    status: str
    mode: str
    company_slug: str | None
    query: str
    evidence: list[dict] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)

    @property
    def company_name(self) -> str | None:
        return COMPANY_NAMES.get(self.company_slug) if self.company_slug else None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "mode": self.mode,
            "company_slug": self.company_slug,
            "company_name": self.company_name,
            "query": self.query,
            "evidence": self.evidence,
            "diagnostics": self.diagnostics,
        }


# ── 向量后端 ────────────────────────────────────────────────────────────
class ChromaVectorStore:
    """Chroma + Ollama 的只读后端。

    客户端惰性创建：只有真正发起查询时才连接，导入模块不会连接任何服务。
    只使用 `get` 与 `similarity_search_with_score` 两个只读接口，
    不调用 add / delete_collection / update。
    """

    def __init__(
        self,
        index_dir: str | Path | None = None,
        collection_name: str = COLLECTION_NAME,
        embedding_model: str = EMBEDDING_MODEL,
    ) -> None:
        self._index_dir = Path(index_dir) if index_dir is not None else DEFAULT_INDEX_DIR
        self._collection_name = collection_name
        self._embedding_model = embedding_model
        self._store: Chroma | None = None

    @property
    def index_dir(self) -> Path:
        return self._index_dir

    def _get_store(self) -> Chroma:
        if self._store is None:
            if not self._index_dir.exists():
                raise FileNotFoundError(f"索引目录不存在：{self._index_dir}")
            self._store = Chroma(
                collection_name=self._collection_name,
                embedding_function=OllamaEmbeddings(model=self._embedding_model),
                persist_directory=str(self._index_dir),
            )
        return self._store

    @staticmethod
    def _to_record(metadata: dict, page_content: str) -> dict:
        text = page_content or ""
        note = text.split("证据：", 1)[-1].strip() if "证据：" in text else text.strip()
        return {
            "job_id": metadata.get("job_id"),
            "source_id": metadata.get("source_id"),
            "company_slug": metadata.get("company_slug"),
            "skill": metadata.get("skill"),
            "requirement_type": metadata.get("requirement_type"),
            "context": metadata.get("context"),
            "importance": metadata.get("importance"),
            "level": metadata.get("level"),
            "note": note,
        }

    def all_records(self, company_slug: str | None = None) -> list[dict]:
        """取回适用范围内的**全部**记录（不做相似度排序）。"""
        store = self._get_store()
        where = {"company_slug": company_slug} if company_slug else None
        raw = store.get(where=where)
        return [
            self._to_record(m, d)
            for m, d in zip(raw.get("metadatas") or [], raw.get("documents") or [])
        ]

    def search(
        self,
        query: str,
        k: int,
        company_slug: str | None = None,
        source_ids=None,
    ) -> list[tuple[dict, float]]:
        """向量检索，返回 [(record, L2距离)] —— 距离越小越相似。

        ``source_ids`` 非空时，Chroma 侧同时按 ``source_id`` 白名单收窄（与公司取交集），
        保证"只匹配某一份 JD"时向量候选在**进入 `_merge` 之前**就已限定在该 JD 范围内。
        """
        store = self._get_store()
        filter_ = metadata_filter(company_slug, source_ids)
        hits = store.similarity_search_with_score(query, k=k, filter=filter_)
        return [(self._to_record(doc.metadata, doc.page_content), float(score)) for doc, score in hits]


# ── 技能词表 ────────────────────────────────────────────────────────────
class SkillVocabulary:
    """技能词表：从岗位画像 YAML 读取技能名，用于"技能精确检索"。

    也可以直接用 `skill_names=` 注入内存词表，便于测试。
    除字面名称外，还带别名/上位词（`SKILL_ALIASES`），使"开发框架""MCP"这类
    与原文用词不同的问法也能走确定性路径。
    """

    def __init__(
        self,
        skill_names: list[str] | None = None,
        profile_path: str | Path | None = None,
    ) -> None:
        if skill_names is not None:
            self._names = list(skill_names)
        else:
            path = Path(profile_path) if profile_path is not None else DEFAULT_PROFILE_PATH
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            self._names = [s["skill"] for s in data.get("skills", []) if s.get("skill")]
        # 只为"词表里确实存在的技能"启用别名：目标技能不存在时别名直接失效，
        # 避免把查询引向知识库里根本没有的技能。
        present = set(self._names)
        self._aliases = {
            canonical: tuple(variants)
            for canonical, variants in SKILL_ALIASES.items()
            if canonical in present
        }

    @property
    def names(self) -> list[str]:
        return list(self._names)

    @property
    def aliases(self) -> dict[str, tuple[str, ...]]:
        return dict(self._aliases)

    @staticmethod
    def _variants(name: str) -> set[str]:
        """技能名的字面匹配变体。含 "/" 的名称额外拆成各部分（如 LangChain / LangGraph）。"""
        variants = {name}
        if "/" in name:
            variants.update(p.strip() for p in name.split("/") if p.strip())
        return {v for v in variants if v}

    @staticmethod
    def _contains(haystack: str, needle: str) -> bool:
        return _contains_term(haystack, needle)

    def match_detailed(self, query: str) -> list[tuple[str, str]]:
        """返回 [(技能名, "literal"|"alias")]。字面命中优先，长名称优先。"""
        if not query:
            return []
        lowered = query.lower()
        found: list[tuple[str, str]] = []
        for name in sorted(self._names, key=len, reverse=True):
            if any(self._contains(lowered, v.lower()) for v in self._variants(name)):
                found.append((name, "literal"))

        literal = {name for name, _ in found}
        alias_only: list[tuple[str, str]] = []
        for canonical, variants in sorted(
            self._aliases.items(), key=lambda kv: -max(len(v) for v in kv[1])
        ):
            if canonical in literal:
                continue
            if any(self._contains(lowered, v.lower()) for v in variants):
                alias_only.append((canonical, "alias"))
        return found + alias_only

    def match(self, query: str) -> list[str]:
        """返回 query 中命中的技能名（含别名命中的技能）。"""
        return [name for name, _ in self.match_detailed(query)]


# ── 检索器 ──────────────────────────────────────────────────────────────
class JobKnowledgeRetriever:
    """岗位知识库检索器。

    三种回答方式（`diagnostics["match_kind"]`）：
    - **exact_skill**：query 里出现技能名或其别名 → 在适用范围的**全量记录**里取
      这些技能的全部证据（保证完整性，含 bonus / preferred）。
    - **vector_only**：query 有实质内容词且能在资料里找到 → 按语义排序返回，
      并做同源合并，避免一句原文的多个切片占满 Top-K。
    - **overview**：query 没有指向任何具体事项 → 按技能聚合回答；跨公司时按
      「覆盖公司数 → 重要性 → 证据条数」排序，体现共性，而不是返回向量 Top-K。

    若 query 有实质内容词但资料里一个都找不到，则判 `not_mentioned`：
    这是基于**全量记录的词面核对**，而不是某个距离阈值。
    """

    def __init__(
        self,
        vector_store=None,
        vocabulary: SkillVocabulary | None = None,
        job_id: str = DEFAULT_JOB_ID,
    ) -> None:
        self._vector = vector_store if vector_store is not None else ChromaVectorStore()
        self._vocab = vocabulary if vocabulary is not None else SkillVocabulary()
        self._job_id = job_id

    # -- 内部工具 ------------------------------------------------------
    @staticmethod
    def _evidence_key(record: dict) -> tuple:
        return (
            record.get("source_id"),
            record.get("skill"),
            record.get("requirement_type"),
            record.get("context"),
            record.get("note"),
        )

    @staticmethod
    def _note_key(record: dict) -> tuple:
        """"同一句原文"的标识：来源 + 原文（不含技能名）。"""
        return (record.get("source_id"), _norm_note(record.get("note")))

    def _safe_search(self, query: str, k: int, company_slug: str | None,
                     source_ids, errors: list[str]):
        """向量检索的容错包装：失败不抛出，只记入 diagnostics。

        ``source_ids`` 原样透传给后端，由后端在**取数时**就限定范围 —— 这里不做
        事后过滤，避免"先混入再剔除"造成的候选污染。
        """
        try:
            return self._vector.search(query, k, company_slug, source_ids=source_ids)
        except Exception as exc:  # Ollama 未启动、索引损坏等
            errors.append(f"vector_search_failed: {type(exc).__name__}: {exc}")
            return []

    def _match_content_units(
        self,
        units: list[ContentUnit],
        scope: list[dict],
        alias_words: tuple[str, ...],
    ) -> tuple[list[bool], set[str], list[str], list[str], list[str], list[str]]:
        """逐个内容单元核对适用范围的全量记录。

        返回 ``(每个单元是否命中, 命中的技能集合, 命中的探针, 未命中单元, 未命中探针, 靠别名解析的单元)``。

        判定粒度是**单元**而不是单个探针：单元里只要有一个探针在资料里出现，
        或者单元本身命中技能别名/上位词表（与 `SkillVocabulary` 共用同一张表），
        就算命中。因此「AI 量子计算经验」里的 `ai` 不能替 `量子计算经验` 解围。
        """
        texts = [(r.get("skill"), _record_text(r)) for r in scope]
        flags: list[bool] = []
        matched_skills: set[str] = set()
        literal_probes: list[str] = []
        unmatched_units: list[str] = []
        unmatched_probes: list[str] = []
        alias_units: list[str] = []

        for unit in units:
            probe_hits: list[str] = []
            for probe in unit.probes:
                hit = False
                for skill, text in texts:
                    if _contains_term(text, probe):
                        hit = True
                        # 不 break：一个探针可能同时出现在多个技能的记录里，
                        # 收敛度（横跨几个技能）正是靠把它们全部收齐才算得准。
                        if skill:
                            matched_skills.add(skill)
                if hit:
                    probe_hits.append(probe)
            via_alias = _alias_hit(unit.text, alias_words)
            matched = bool(probe_hits) or via_alias
            flags.append(matched)

            for probe in probe_hits:
                if probe not in literal_probes:
                    literal_probes.append(probe)
            if via_alias and unit.text not in alias_units:
                alias_units.append(unit.text)
            if not matched:
                unmatched_units.append(unit.text)
                for probe in unit.probes:
                    if probe not in unmatched_probes:
                        unmatched_probes.append(probe)
        return flags, matched_skills, literal_probes, unmatched_units, unmatched_probes, alias_units

    def _merge(
        self,
        exact: list[dict],
        vector_hits: list[tuple[dict, float]],
        terms: list[str],
        alias_terms: frozenset[str] = frozenset(),
    ) -> list[dict]:
        """合并精确结果与向量结果，按完整证据去重，并标注来源方式。"""
        merged: dict[tuple, dict] = {}
        for record in exact:
            merged[self._evidence_key(record)] = {**record, "origin": "skill_exact", "distance": None}

        for record, distance in vector_hits:
            # 向量结果里与该查询技能无关的候选不作为证据（转由调用方在 diagnostics 中查看）
            if record.get("skill") not in terms:
                continue
            key = self._evidence_key(record)
            if key in merged:
                merged[key]["origin"] = "both"
                merged[key]["distance"] = distance
            else:
                merged[key] = {**record, "origin": "vector", "distance": distance}

        order = {"both": 0, "skill_exact": 1, "vector": 2}
        return sorted(
            merged.values(),
            key=lambda e: (
                # 命中方式与要求性质、重要性都排在别名之前 —— 别名只是"措辞贴近"，
                # 不能无条件压过 required、也不能把 preferred/bonus 挤到硬性要求前面。
                order.get(e.get("origin"), 9),
                _RT_RANK.get(e.get("requirement_type"), 9),
                -(e.get("importance") or 0),
                0 if e.get("skill") in alias_terms else 1,
                e.get("distance") if e.get("distance") is not None else float("inf"),
                e.get("skill") or "",
            ),
        )

    def _collapse_shared_notes(
        self,
        evidence: list[dict],
        scope: list[dict],
        protected_skills: frozenset[str] = frozenset(),
    ) -> list[dict]:
        """合并同源重复：同一来源的同一句原文，只保留一条证据条目。

        同一句 JD 原文常常同时是多个技能的证据（例如"熟悉 Prompt、RAG、Embedding、
        Agent、Function Calling 等概念"）。若不合并，这一句话的多个切片会各占一个
        Top-K 名额，稀释真正不同的信息（这条只影响没有点名技能的语义检索路径）。

        **被查询点名的技能受保护**（``protected_skills``）：只要用户明确问了某个技能，
        它就必须留下自己的可追溯证据，不能用 ``also_supports`` 代替。否则会出现
        「问了计算机网络和操作系统，回来的只有操作系统」这种整块丢证据的情况
        —— 而且谁存活取决于技能名的字符序，用户无法预测。

        **不合并**同一来源、同一原文但 ``requirement_type`` 不同的证据：
        "岗位需要做这件事"（required）与"此前做过是加分"（bonus）是两回事。
        被合并掉的技能名记入保留项的 ``also_supports``。
        """
        shared: dict[tuple, set[str]] = {}
        for record in scope:
            shared.setdefault(self._note_key(record), set()).add(record.get("skill"))

        kept: dict[tuple, dict] = {}
        for item in evidence:
            key = self._note_key(item) + (item.get("requirement_type"),)
            if item.get("skill") in protected_skills:
                key = key + (item.get("skill"),)
            if key in kept:
                continue  # evidence 已按优先级排序，先到者胜
            kept[key] = dict(item)

        for key, item in kept.items():
            others = sorted(
                skill for skill in shared.get(self._note_key(item), set())
                if skill and skill != item.get("skill")
            )
            if others:
                item["also_supports"] = others
        return list(kept.values())

    # -- 整体性问题：按技能聚合 ------------------------------------------
    def _skill_groups(self, scope: list[dict]) -> list[dict]:
        """把适用范围的记录按技能分组，并给出聚合统计与代表性证据。"""
        groups: dict[str, list[dict]] = {}
        for record in scope:
            groups.setdefault(record.get("skill"), []).append(record)

        # 同一句原文被几个技能引用 —— 越少越"专属"，越适合作为代表证据
        share: dict[tuple, int] = {}
        for record in scope:
            key = self._note_key(record)
            share[key] = share.get(key, 0) + 1

        out = []
        for skill, records in groups.items():
            companies = sorted({r.get("company_slug") for r in records if r.get("company_slug")})
            rts = sorted({r.get("requirement_type") for r in records if r.get("requirement_type")})
            out.append({
                "skill": skill,
                "companies": companies,
                "requirement_types": rts,
                "count": len(records),
                "importance": max((r.get("importance") or 0) for r in records),
                "records": records,
                "representatives": sorted(
                    records,
                    key=lambda r: (
                        _RT_RANK.get(r.get("requirement_type"), 9),
                        share.get(self._note_key(r), 0),
                        -len(_norm_note(r.get("note"))),
                        r.get("source_id") or "",
                    ),
                ),
            })

        # 跨公司覆盖度优先：三家都要求的技能，比单家公司的冷门技能更能代表"通常要求"
        out.sort(key=lambda g: (-len(g["companies"]), -g["importance"], -g["count"], g["skill"] or ""))
        return out

    def _overview_evidence(
        self,
        groups: list[dict],
        scope: list[dict],
        top_k: int,
        jd_count: int,
    ) -> list[dict]:
        """每个技能取一条代表证据；原文已被别的技能占用时跳过，保证信息不重复。

        ``used`` 的键含 ``requirement_type``，与 `_collapse_shared_notes` 保持一致，
        免得"某句原文同时是 A 的 required、B 的 bonus"时把 B 挤掉。

        每条结果都带上 ``jd_count``（样本内 JD 份数）与 ``companies``（覆盖公司），
        让调用方看得见"这是 3 份 JD 的样本"，不会误当成整个行业的共性。
        """
        used: set[tuple] = set()
        evidence: list[dict] = []
        for group in groups:
            if len(evidence) >= top_k:
                break
            pick = None
            for record in group["representatives"]:
                if self._note_key(record) + (record.get("requirement_type"),) not in used:
                    pick = record
                    break
            if pick is None:
                continue  # 该技能的证据原文已被更重要的技能代表，跳过以免重复占位
            used.add(self._note_key(pick) + (pick.get("requirement_type"),))
            item = {
                **pick,
                "origin": "overview",
                "distance": None,
                "companies": group["companies"],
                "requirement_types": group["requirement_types"],
                "jd_count": jd_count,
            }
            others = sorted({
                record.get("skill")
                for record in scope
                if self._note_key(record) == self._note_key(pick)
                and record.get("skill")
                and record.get("skill") != pick.get("skill")
            })
            if others:
                item["also_supports"] = others
            evidence.append(item)
        return evidence

    # -- 主入口 --------------------------------------------------------
    def retrieve(self, request: RetrieveRequest) -> RetrieveResult:
        query = (request.query or "").strip()
        if not query:
            raise ValueError("query 不能为空")

        top_k = request.top_k
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError(f"top_k 必须是 >=1 的整数，收到 {top_k!r}")

        mode = request.mode or MODE_AUTO
        if mode not in MODES:
            raise ValueError(f"mode 必须是 {MODES} 之一，收到 {mode!r}")

        job_id = request.job_id or self._job_id
        errors: list[str] = []
        diagnostics: dict = {"job_id": job_id, "requested_mode": mode, "errors": errors}

        # 1) 公司解析：显式指定优先，其次从 query 识别
        explicit: str | None = None
        if request.company is not None and str(request.company).strip():
            explicit = resolve_company(request.company)
            if explicit is None:
                raise ValueError(f"无法识别的公司：{request.company!r}")

        detected = detect_companies(query)
        diagnostics["detected_companies"] = detected

        if explicit is not None:
            company_slug, resolved_mode = explicit, MODE_COMPANY
        elif len(detected) > 1:
            diagnostics["reason"] = "查询涉及多家公司，需要澄清后再检索，未混合任何公司证据"
            return RetrieveResult(
                status=STATUS_AMBIGUOUS, mode=MODE_AUTO, company_slug=None,
                query=query, evidence=[], diagnostics=diagnostics,
            )
        elif len(detected) == 1:
            company_slug, resolved_mode = detected[0], MODE_COMPANY
        else:
            company_slug, resolved_mode = None, MODE_FAMILY

        if mode != MODE_AUTO:
            resolved_mode = mode
            if mode == MODE_FAMILY:
                company_slug = None
            elif mode == MODE_COMPANY and company_slug is None:
                raise ValueError("mode=company_specific 需要指定 company，或在 query 中写明公司名称")

        diagnostics["company_slug"] = company_slug
        diagnostics["company_name"] = COMPANY_NAMES.get(company_slug) if company_slug else None

        # 2) 取回适用范围内的全量记录（not_mentioned 必须基于全量判断，而非 Top-K）
        try:
            scope = self._vector.all_records(company_slug)
        except FileNotFoundError as exc:
            diagnostics["reason"] = "index_missing"
            errors.append(str(exc))
            return RetrieveResult(
                status=STATUS_NO_SOURCE, mode=resolved_mode, company_slug=company_slug,
                query=query, evidence=[], diagnostics=diagnostics,
            )
        except Exception as exc:
            diagnostics["reason"] = "index_unavailable"
            errors.append(f"{type(exc).__name__}: {exc}")
            return RetrieveResult(
                status=STATUS_NO_SOURCE, mode=resolved_mode, company_slug=company_slug,
                query=query, evidence=[], diagnostics=diagnostics,
            )

        scope = [r for r in scope if not r.get("job_id") or r.get("job_id") == job_id]
        # 阶段四扩展：按 source_id 精确定位单份真实 JD。只在显式指定时过滤，
        # 不指定则完全维持阶段二的检索行为（不跨公司、全量核对等）。
        requested_source = (request.source_id or "").strip() or None
        diagnostics["source_id"] = requested_source
        # 向量检索侧的同一道白名单：不只是过滤 scope，还要让后端在取数时就限定范围
        allowed_sources = frozenset({requested_source}) if requested_source else None
        if requested_source:
            scope = [r for r in scope if r.get("source_id") == requested_source]
        diagnostics["scope_count"] = len(scope)
        diagnostics["sources_included"] = sorted({r.get("source_id") for r in scope if r.get("source_id")})

        if not scope:
            diagnostics["reason"] = (
                f"来源 {requested_source!r} 没有索引记录"
                if requested_source
                else (
                    f"公司 {company_slug!r} 没有索引记录"
                    if company_slug else f"岗位 {job_id!r} 没有索引记录"
                )
            )
            return RetrieveResult(
                status=STATUS_NO_SOURCE, mode=resolved_mode, company_slug=company_slug,
                query=query, evidence=[], diagnostics=diagnostics,
            )

        # 3) 技能精确检索（含别名/上位词）
        matches = self._vocab.match_detailed(query)
        terms = [name for name, _ in matches]
        alias_terms = frozenset(name for name, origin in matches if origin == "alias")
        diagnostics["skill_terms"] = terms
        diagnostics["skill_term_origins"] = {name: origin for name, origin in matches}
        diagnostics["alias_terms"] = sorted(alias_terms)

        if terms:
            exact = [r for r in scope if r.get("skill") in terms]
            vector_hits = self._safe_search(query, top_k, company_slug, allowed_sources, errors)
            if not exact:
                diagnostics["reason"] = (
                    f"已核对适用范围内全部 {len(scope)} 条记录，未发现技能 {terms} 的明确证据"
                )
                diagnostics["vector_candidates"] = [r for r, _ in vector_hits]
                return RetrieveResult(
                    status=STATUS_NOT_MENTIONED, mode=resolved_mode, company_slug=company_slug,
                    query=query, evidence=[], diagnostics=diagnostics,
                )
            merged = self._merge(exact, vector_hits, terms, alias_terms)
            # 点名了的技能受保护：共享原文不得让其中任何一个丢掉证据
            evidence = self._collapse_shared_notes(merged, scope, frozenset(terms))
            diagnostics["vector_candidates"] = [r for r, _ in vector_hits if r.get("skill") not in terms]
            diagnostics["match_kind"] = "exact_skill"
            diagnostics["evidence_skills"] = sorted({e.get("skill") for e in evidence if e.get("skill")})
            return RetrieveResult(
                status=STATUS_MATCHED, mode=resolved_mode, company_slug=company_slug,
                query=query, evidence=evidence, diagnostics=diagnostics,
            )

        # 4) 无技能词 —— 按「内容单元」核对资料里到底有没有这个主题
        units = extract_content_units(query)
        alias_words = tuple(
            word.lower() for variants in self._vocab.aliases.values() for word in variants
        )
        (unit_flags, matched_skills, matched_probes,
         unmatched_units, unmatched_probes, alias_units) = self._match_content_units(units, scope, alias_words)
        diagnostics["content_units"] = [u.text for u in units]
        diagnostics["content_terms"] = [p for u in units for p in u.probes]
        diagnostics["matched_content_terms"] = matched_probes
        diagnostics["unmatched_content_terms"] = unmatched_probes
        diagnostics["unmatched_content_units"] = unmatched_units
        diagnostics["alias_resolved_units"] = alias_units
        diagnostics["matched_skills_from_content"] = sorted(s for s in matched_skills if s)

        # 4a) 有内容单元**完全**没命中 —— 保守判定为未提及，绝不拿无关向量结果当证据。
        #     判据落在"整个单元"上，所以通用词（如 AI）命中不会抵消核心主题的完全未命中。
        if unmatched_units:
            vector_hits = self._safe_search(query, _candidate_k(top_k), company_slug, allowed_sources, errors)
            diagnostics["match_kind"] = "term_scan"
            diagnostics["reason"] = (
                f"已核对适用范围内全部 {len(scope)} 条记录，"
                f"未发现查询主题 {unmatched_units} 的任何证据"
            )
            diagnostics["note"] = _NO_EVIDENCE_NOTE
            diagnostics["vector_candidates"] = [r for r, _ in vector_hits]
            return RetrieveResult(
                status=STATUS_NOT_MENTIONED, mode=resolved_mode, company_slug=company_slug,
                query=query, evidence=[], diagnostics=diagnostics,
            )

        # 5) 整体性问题（不问具体事项）—— 按技能聚合，而不是向量 Top-K
        if is_overview_query(query, units, matched_skills):
            jd_count = len(diagnostics["sources_included"])
            groups = self._skill_groups(scope)
            evidence = self._overview_evidence(groups, scope, top_k, jd_count)
            diagnostics["match_kind"] = "overview"
            diagnostics["skill_summary"] = [
                {
                    "skill": g["skill"],
                    "companies": g["companies"],
                    "requirement_types": g["requirement_types"],
                    "count": g["count"],
                    "importance": g["importance"],
                }
                for g in groups
            ]
            diagnostics["company_distribution"] = {
                slug: sum(1 for r in scope if r.get("company_slug") == slug)
                for slug in sorted({r.get("company_slug") for r in scope if r.get("company_slug")})
            }
            diagnostics["sample_scope"] = {
                "jd_count": jd_count,
                "sources": list(diagnostics["sources_included"]),
                "companies": sorted({r.get("company_slug") for r in scope if r.get("company_slug")}),
                "company_scope_auto_detected": resolved_mode == MODE_FAMILY and mode == MODE_AUTO,
                "caveat": (
                    f"仅基于当前 {jd_count} 份 JD 样本，样本量很小："
                    "只能说明这几个样本里的分布，不能代表整个行业的共性，"
                    "也不代表任何一家公司的硬性门槛。"
                ),
            }
            diagnostics["note"] = (
                "整体性问题：按技能聚合回答。排序依据是「覆盖公司数 → 重要性 → 证据条数」，"
                "不是向量距离；evidence 每个技能只取一条代表证据，避免同一句原文重复占位。"
                f"结果只在当前 {jd_count} 份 JD 样本内成立（见 sample_scope），"
                "每条 evidence 都带 companies / requirement_types / jd_count，"
                "不代表整个行业，也不代表任一公司的硬性门槛。"
            )
            if not evidence:
                diagnostics["reason"] = "适用范围内没有可聚合的技能记录"
                return RetrieveResult(
                    status=STATUS_NOT_MENTIONED, mode=resolved_mode, company_slug=company_slug,
                    query=query, evidence=[], diagnostics=diagnostics,
                )
            return RetrieveResult(
                status=STATUS_MATCHED, mode=resolved_mode, company_slug=company_slug,
                query=query, evidence=evidence, diagnostics=diagnostics,
            )

        # 6) 有内容词且资料里找得到 —— 语义排序，并合并同源重复
        vector_hits = self._safe_search(query, _candidate_k(top_k), company_slug, allowed_sources, errors)
        diagnostics["match_kind"] = "vector_only"
        diagnostics["note"] = (
            "查询中没有技能名，但有能在资料中找到的内容词，结果按向量相似度排序；"
            "已按「同一来源 + 同一原文 + 同一要求性质」合并近重复，"
            "L2 距离未使用固定阈值，调用方需自行判断相关性。"
        )
        if not vector_hits:
            diagnostics["reason"] = "向量检索未返回任何结果"
            return RetrieveResult(
                status=STATUS_NOT_MENTIONED, mode=resolved_mode, company_slug=company_slug,
                query=query, evidence=[], diagnostics=diagnostics,
            )
        raw = [{**r, "origin": "vector", "distance": d} for r, d in vector_hits]
        evidence = self._collapse_shared_notes(raw, scope)[:top_k]
        return RetrieveResult(
            status=STATUS_MATCHED, mode=resolved_mode, company_slug=company_slug,
            query=query, evidence=evidence, diagnostics=diagnostics,
        )


def retrieve(
    query: str,
    company: str | None = None,
    job_id: str = DEFAULT_JOB_ID,
    top_k: int = DEFAULT_TOP_K,
    mode: str = MODE_AUTO,
    source_id: str | None = None,
    retriever: JobKnowledgeRetriever | None = None,
) -> RetrieveResult:
    """便捷函数：一次性检索。默认使用真实的 Chroma + Ollama 后端。"""
    engine = retriever if retriever is not None else JobKnowledgeRetriever()
    request = RetrieveRequest(
        query=query, company=company, job_id=job_id, top_k=top_k, mode=mode,
        source_id=source_id,
    )
    return engine.retrieve(request)