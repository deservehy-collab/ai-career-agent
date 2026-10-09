"""agents/retriever.py 的单元测试（标准库 unittest，不依赖 pytest）。

隔离策略
--------
- 向量后端：注入 `FakeVectorStore` 内存实现，**不连接 Chroma、不调用 Ollama**。
- 技能词表：注入内存技能名列表，**不读取 YAML**（个别用例显式加载真实 YAML）。
- 真实索引：不打开、不写入、不删除；`test_real_index_is_untouched` 快照比对确认。

运行：
    .venv/Scripts/python.exe -m unittest tests.test_retriever -v
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.retriever import (  # noqa: E402
    COMPANY_ALIASES,
    MODE_COMPANY,
    MODE_FAMILY,
    SKILL_ALIASES,
    STATUS_AMBIGUOUS,
    STATUS_MATCHED,
    STATUS_NOT_MENTIONED,
    STATUS_NO_SOURCE,
    ChromaVectorStore,
    JobKnowledgeRetriever,
    RetrieveRequest,
    SkillVocabulary,
    detect_companies,
    extract_content_terms,
    extract_content_units,
    resolve_company,
)

# ── 测试夹具 ────────────────────────────────────────────────────────────
SKILLS = [
    "Python",
    "RAG",
    "Agent",
    "Docker",
    "Prompt Engineering",
    "LangChain / LangGraph",
    "计算机网络",
    "Git",
]


def record(skill, company, source, note, rt="required", ctx="qualification", importance=3, level="中级"):
    return {
        "job_id": "ai_application_engineer",
        "source_id": source,
        "company_slug": company,
        "skill": skill,
        "requirement_type": rt,
        "context": ctx,
        "importance": importance,
        "level": level,
        "note": note,
    }


H = "jd_hundsun_001"
Z = "jd_zhongzhi_001"
Y = "jd_yisiwei_001"

RECORDS = [
    record("Python", "hundsun", H, "岗位要求2「熟练掌握Python或Java任一语言」", importance=5),
    record("RAG", "hundsun", H, "岗位要求8「了解Prompt工程技巧、RAG检索增强生成核心流程」", importance=5),
    record("计算机网络", "hundsun", H, "岗位要求3「具备扎实的数据结构、算法、计算机网络、操作系统基础」", importance=2),
    record("Python", "zhongzhi", Z, "任职要求2「熟练使用 Python，具备实际工程开发经验」", importance=5),
    record("Docker", "zhongzhi", Z, "加分项「有 Docker、云服务、CI/CD 或生产环境部署经验」", rt="bonus", ctx="bonus_section", importance=2),
    record("Agent", "zhongzhi", Z, "岗位职责2「开发 AI Agent，实践 Prompt 设计」", ctx="responsibility", importance=5),
    record("Agent", "yisiwei", Y, "职位描述1「开发企业级AI智能体（Agent）」", ctx="responsibility", importance=5),
    record("Prompt Engineering", "yisiwei", Y, "职位描述4「开展Prompt Engineering的实验设计与效果优化」", ctx="responsibility", importance=4),
]

# ── 缺陷回归用的扩展夹具（D1 / D2 / D3 / D4）──────────────────────────
# 相对 RECORDS 增加了：别名目标技能、同源原文（一句话支撑多个技能）、
# 以及一条"别家公司有、恒生电子没有"的 Vue 记录，用于验证不跨公司顶替。
EXTRA_SKILLS = SKILLS + [
    "LangChain / LangGraph",
    "Agent Skill / MCP 工具封装",
    "后端 API 开发",
    "Embedding",
    "操作系统",
]

EXTRA_RECORDS = RECORDS + [
    record("LangChain / LangGraph", "zhongzhi", Z,
           "加分项「使用过 LangChain、LangGraph、LlamaIndex 或其他 Agent、RAG 开发框架」",
           rt="bonus", ctx="bonus_section", importance=3),
    record("LangChain / LangGraph", "hundsun", H,
           "岗位要求9「有Hugging Face、LangChain等大模型开发工具使用经验…者优先」",
           rt="preferred", importance=3),
    record("测试与效果评测", "zhongzhi", Z,
           "加分项「有 AI 应用评测、Agent Trace、可观测性、权限控制、上下文管理或异常恢复经验」",
           rt="bonus", ctx="bonus_section", importance=4),
    record("Agent Skill / MCP 工具封装", "zhongzhi", Z,
           "岗位职责4「将内部 API、数据服务和业务能力封装为可复用的 Agent Skill 或 MCP 工具」",
           rt="required", ctx="responsibility", importance=3),
    record("Agent Skill / MCP 工具封装", "zhongzhi", Z,
           "加分项「开发过 Agent Skill、MCP Server、AI 全栈应用或其他可展示的相关作品」",
           rt="bonus", ctx="bonus_section", importance=3),
    record("Vue", "zhongzhi", Z, "加分项「有 Vue 前端开发经验」",
           rt="bonus", ctx="bonus_section", importance=1),
    record("RAG", "zhongzhi", Z,
           "岗位职责3「参与 RAG 知识库建设，包括文档处理、检索与 Rerank、效果评测和问题分析」",
           ctx="responsibility", importance=5),
    record("RAG", "zhongzhi", Z,
           "任职要求4「熟悉 Prompt、RAG、Embedding、Agent、Function Calling 等概念」", importance=5),
    record("Agent", "zhongzhi", Z,
           "任职要求4「熟悉 Prompt、RAG、Embedding、Agent、Function Calling 等概念」", importance=5),
    record("Prompt Engineering", "zhongzhi", Z,
           "任职要求4「熟悉 Prompt、RAG、Embedding、Agent、Function Calling 等概念」", importance=4),
    record("Embedding", "zhongzhi", Z,
           "任职要求4「熟悉 Prompt、RAG、Embedding、Agent、Function Calling 等概念」", importance=3),
    # 计算机网络（RECORDS 里已有）与操作系统共享同一来源的同一句原文 —— F1 的回归素材
    record("操作系统", "hundsun", H,
           "岗位要求3「具备扎实的数据结构、算法、计算机网络、操作系统基础」", importance=2),
    # 后端侧说法的正确落点（F2）
    record("后端 API 开发", "hundsun", H,
           "岗位要求5「了解Python（Flask/FastAPI）或Java（SpringBoot）后端框架者优先」",
           rt="preferred", importance=4),
    # 让语料里出现"应用开发"，与真实索引一致（F6 的收敛度判据需要）
    record("Agent", "yisiwei", Y,
           "任职要求3「了解大语言模型（LLM）应用开发的基本概念，包括RAG、Function Calling、Agent架构等」",
           importance=5),
]


def count_records(company_slug):
    """夹具里某公司的记录数 —— 避免把夹具规模硬编码进断言。"""
    return sum(1 for r in EXTRA_RECORDS if r["company_slug"] == company_slug)


class FakeVectorStore:
    """内存向量后端：不连接 Chroma/Ollama。"""

    def __init__(self, records, search_plan=None):
        self.records = list(records)
        self.search_plan = search_plan  # 可选：手工指定 (record, distance) 列表
        self.all_records_calls = []
        self.search_calls = []

    def all_records(self, company_slug=None):
        self.all_records_calls.append(company_slug)
        if company_slug:
            return [r for r in self.records if r["company_slug"] == company_slug]
        return list(self.records)

    def search(self, query, k, company_slug=None):
        self.search_calls.append((query, k, company_slug))
        if self.search_plan is not None:
            return self.search_plan[:k]
        pool = [r for r in self.records if not company_slug or r["company_slug"] == company_slug]
        return [(r, float(i) / 10.0) for i, r in enumerate(pool[:k])]


class FakeFailingVectorStore(FakeVectorStore):
    """模拟索引不可用。"""

    def __init__(self, exc):
        super().__init__([])
        self._exc = exc

    def all_records(self, company_slug=None):
        raise self._exc


def make_retriever(records=None, search_plan=None, skills=None):
    store = FakeVectorStore(records if records is not None else RECORDS, search_plan=search_plan)
    vocab = SkillVocabulary(skill_names=skills if skills is not None else SKILLS)
    return JobKnowledgeRetriever(vector_store=store, vocabulary=vocab), store


# ── 1/2. 公司名称与简称识别 ─────────────────────────────────────────────
class TestCompanyDetection(unittest.TestCase):
    def test_full_names(self):
        self.assertEqual(detect_companies("恒生电子股份有限公司"), ["hundsun"])
        self.assertEqual(detect_companies("北京众智诚坚科技有限公司"), ["zhongzhi"])
        self.assertEqual(detect_companies("易思维（杭州）科技有限公司"), ["yisiwei"])

    def test_short_names(self):
        self.assertEqual(detect_companies("恒生怎么样"), ["hundsun"])
        self.assertEqual(detect_companies("众智诚坚怎么样"), ["zhongzhi"])
        self.assertEqual(detect_companies("易思维怎么样"), ["yisiwei"])

    def test_slug_passthrough(self):
        self.assertEqual(detect_companies("tell me about hundsun"), ["hundsun"])
        self.assertEqual(detect_companies("yisiwei 要求"), ["yisiwei"])

    def test_halfwidth_parens_variant(self):
        self.assertEqual(detect_companies("易思维(杭州)科技"), ["yisiwei"])

    def test_no_company(self):
        self.assertEqual(detect_companies("AI 应用开发岗位要求什么技能"), [])

    def test_empty_query(self):
        self.assertEqual(detect_companies(""), [])
        self.assertEqual(detect_companies(None), [])


class TestLongestMatchFirst(unittest.TestCase):
    def test_long_name_wins_and_slug_not_duplicated(self):
        """长公司名优先：全称只识别出一个 slug，不会因含短别名而重复计数。"""
        self.assertEqual(detect_companies("北京众智诚坚科技有限公司"), ["zhongzhi"])
        self.assertEqual(detect_companies("易思维（杭州）科技"), ["yisiwei"])

    def test_longest_alias_is_listed_first(self):
        for slug, aliases in COMPANY_ALIASES.items():
            lengths = [len(a) for a in aliases]
            self.assertEqual(lengths, sorted(lengths, reverse=True), f"{slug} 别名未按长度降序")

    def test_resolve_company(self):
        self.assertEqual(resolve_company("恒生电子"), "hundsun")
        self.assertEqual(resolve_company("北京众智诚坚科技"), "zhongzhi")
        self.assertEqual(resolve_company("yisiwei"), "yisiwei")
        self.assertIsNone(resolve_company("不存在的公司"))
        self.assertIsNone(resolve_company(""))
        self.assertIsNone(resolve_company(None))


# ── 3/4. 多公司歧义与显式公司过滤 ───────────────────────────────────────
class TestAmbiguousAndFiltering(unittest.TestCase):
    def test_multi_company_query_is_ambiguous(self):
        r, store = make_retriever()
        result = r.retrieve(RetrieveRequest(query="恒生电子和易思维哪个对 Agent 要求更高？"))
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.evidence, [])
        self.assertEqual(sorted(result.diagnostics["detected_companies"]), ["hundsun", "yisiwei"])
        # 歧义时不应做任何范围查询
        self.assertEqual(store.all_records_calls, [])

    def test_explicit_company_never_mixes_others(self):
        r, _ = make_retriever()
        for name, slug in (("恒生电子", "hundsun"), ("北京众智诚坚科技", "zhongzhi"), ("易思维", "yisiwei")):
            with self.subTest(company=name):
                result = r.retrieve(RetrieveRequest(query="要求什么技能", company=name))
                self.assertEqual(result.company_slug, slug)
                self.assertTrue(result.evidence)
                self.assertEqual({e["company_slug"] for e in result.evidence}, {slug})

    def test_explicit_company_overrides_query_mention(self):
        """显式传入公司时以参数为准，不因 query 里出现别家公司而歧义。"""
        r, _ = make_retriever()
        result = r.retrieve(RetrieveRequest(query="恒生电子和易思维对比", company="恒生电子"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.company_slug, "hundsun")
        self.assertEqual({e["company_slug"] for e in result.evidence}, {"hundsun"})

    def test_company_detected_from_query(self):
        r, store = make_retriever()
        r.retrieve(RetrieveRequest(query="恒生电子要求 RAG 吗"))
        self.assertEqual(store.all_records_calls, ["hundsun"])

    def test_job_family_mode_uses_all_sources(self):
        r, store = make_retriever()
        result = r.retrieve(RetrieveRequest(query="恒生电子要求什么", mode=MODE_FAMILY))
        self.assertEqual(result.mode, MODE_FAMILY)
        self.assertEqual(store.all_records_calls, [None])
        self.assertGreaterEqual(len(result.diagnostics["sources_included"]), 2)

    def test_company_mode_requires_company(self):
        r, _ = make_retriever()
        with self.assertRaises(ValueError):
            r.retrieve(RetrieveRequest(query="要求什么技能", mode=MODE_COMPANY))


# ── 5/6. 两种检索合并 + 去重 ────────────────────────────────────────────
class TestMergeAndDedup(unittest.TestCase):
    def test_skill_exact_hit(self):
        r, _ = make_retriever()
        result = r.retrieve(RetrieveRequest(query="Python 要学到什么程度"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.diagnostics["skill_terms"], ["Python"])
        self.assertEqual({e["skill"] for e in result.evidence}, {"Python"})

    def test_exact_result_includes_all_types_not_just_topk(self):
        """精确检索必须返回该技能的**全部**证据（含 bonus），不受 top_k 限制。"""
        r, _ = make_retriever()
        result = r.retrieve(RetrieveRequest(query="Docker", top_k=1))
        self.assertEqual({e["skill"] for e in result.evidence}, {"Docker"})
        self.assertEqual(result.evidence[0]["requirement_type"], "bonus")

    def test_merge_marks_both_and_dedups(self):
        """向量结果与精确结果命中同一条时，只保留一条并标为 both。"""
        plan = [(RECORDS[0], 0.42)]  # Python / hundsun，与精确结果重复
        r, _ = make_retriever(search_plan=plan)
        result = r.retrieve(RetrieveRequest(query="恒生电子 Python"))
        pythons = [e for e in result.evidence if e["skill"] == "Python"]
        self.assertEqual(len(pythons), 1)
        self.assertEqual(pythons[0]["origin"], "both")
        self.assertAlmostEqual(pythons[0]["distance"], 0.42)

    def test_vector_only_hits_are_excluded_from_evidence(self):
        """向量结果中与查询技能无关的候选，不作为证据（转 diagnostics）。"""
        plan = [(RECORDS[2], 0.10), (RECORDS[0], 0.90)]  # 计算机网络(无关) + Python
        r, _ = make_retriever(search_plan=plan)
        result = r.retrieve(RetrieveRequest(query="恒生电子 Python"))
        self.assertEqual({e["skill"] for e in result.evidence}, {"Python"})
        self.assertEqual([c["skill"] for c in result.diagnostics["vector_candidates"]], ["计算机网络"])

    def test_metadata_preserved_in_evidence(self):
        r, _ = make_retriever()
        result = r.retrieve(RetrieveRequest(query="Docker"))
        e = result.evidence[0]
        for key in ("skill", "company_slug", "source_id", "requirement_type", "context", "note", "importance", "level"):
            self.assertIn(key, e)
        self.assertEqual(e["company_slug"], "zhongzhi")
        self.assertEqual(e["context"], "bonus_section")

    def test_slash_skill_name_variants(self):
        v = SkillVocabulary(skill_names=["LangChain / LangGraph"])
        self.assertEqual(v.match("用过 LangChain 吗"), ["LangChain / LangGraph"])
        self.assertEqual(v.match("LangGraph 工作流"), ["LangChain / LangGraph"])

    def test_word_boundary_avoids_false_positive(self):
        v = SkillVocabulary(skill_names=["RAG", "Git", "Python"])
        self.assertEqual(v.match("storage solution"), [])
        self.assertEqual(v.match("digital tools"), [])
        self.assertEqual(sorted(v.match("RAG 与 Git")), ["Git", "RAG"])


# ── 7. 四种状态 ─────────────────────────────────────────────────────────
class TestStatuses(unittest.TestCase):
    def test_matched(self):
        r, _ = make_retriever()
        self.assertEqual(r.retrieve(RetrieveRequest(query="RAG")).status, STATUS_MATCHED)

    def test_not_mentioned_checks_full_scope_not_topk(self):
        """Docker 只存在于 zhongzhi；问 hundsun 的 Docker 应为 not_mentioned。"""
        r, store = make_retriever()
        result = r.retrieve(RetrieveRequest(query="恒生电子要求 Docker 吗"))
        self.assertEqual(result.status, STATUS_NOT_MENTIONED)
        self.assertEqual(result.evidence, [])
        # 必须核对过该公司的全量记录
        self.assertEqual(store.all_records_calls, ["hundsun"])
        self.assertEqual(result.diagnostics["scope_count"], 3)
        self.assertIn("未发现", result.diagnostics["reason"])

    def test_not_mentioned_does_not_leak_other_company(self):
        r, _ = make_retriever()
        result = r.retrieve(RetrieveRequest(query="恒生电子要求 Docker 吗"))
        self.assertEqual(result.status, STATUS_NOT_MENTIONED)
        self.assertEqual(result.evidence, [])          # 不得用 zhongzhi 的 Docker 作答
        self.assertEqual(result.company_slug, "hundsun")

    def test_no_source_when_company_has_no_records(self):
        r, _ = make_retriever(records=[r for r in RECORDS if r["company_slug"] == "zhongzhi"])
        result = r.retrieve(RetrieveRequest(query="要求什么", company="恒生电子"))
        self.assertEqual(result.status, STATUS_NO_SOURCE)
        self.assertEqual(result.evidence, [])

    def test_no_source_when_index_missing(self):
        r = JobKnowledgeRetriever(
            vector_store=FakeFailingVectorStore(FileNotFoundError("索引目录不存在")),
            vocabulary=SkillVocabulary(skill_names=SKILLS),
        )
        result = r.retrieve(RetrieveRequest(query="Python"))
        self.assertEqual(result.status, STATUS_NO_SOURCE)
        self.assertEqual(result.diagnostics["reason"], "index_missing")

    def test_no_source_on_unexpected_backend_error(self):
        r = JobKnowledgeRetriever(
            vector_store=FakeFailingVectorStore(RuntimeError("boom")),
            vocabulary=SkillVocabulary(skill_names=SKILLS),
        )
        result = r.retrieve(RetrieveRequest(query="Python"))
        self.assertEqual(result.status, STATUS_NO_SOURCE)
        self.assertEqual(result.diagnostics["reason"], "index_unavailable")
        self.assertTrue(result.diagnostics["errors"])

    def test_ambiguous_status(self):
        r, _ = make_retriever()
        result = r.retrieve(RetrieveRequest(query="恒生电子 vs 易思维"))
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.evidence, [])

    def test_vector_failure_does_not_break_exact_match(self):
        """Ollama 不可用时，技能精确检索仍应工作（全量记录来自 Chroma.get，不需 embedding）。"""
        class HalfBroken(FakeVectorStore):
            def search(self, query, k, company_slug=None):
                raise ConnectionError("Ollama 未启动")

        r = JobKnowledgeRetriever(vector_store=HalfBroken(RECORDS), vocabulary=SkillVocabulary(skill_names=SKILLS))
        result = r.retrieve(RetrieveRequest(query="Python"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertTrue(result.diagnostics["errors"])

    def test_overview_query_is_flagged(self):
        """整体性问题（无技能词、无内容词）应走 overview 聚合路径。"""
        r, _ = make_retriever()
        result = r.retrieve(RetrieveRequest(query="这个岗位到底要什么"))
        self.assertEqual(result.diagnostics["skill_terms"], [])
        self.assertEqual(result.diagnostics["match_kind"], "overview")
        self.assertIn("note", result.diagnostics)
        self.assertIn("skill_summary", result.diagnostics)


# ── 8. 非法输入与异常处理 ───────────────────────────────────────────────
class TestInvalidInput(unittest.TestCase):
    def setUp(self):
        self.r, _ = make_retriever()

    def test_empty_query(self):
        for bad in ("", "   ", None):
            with self.subTest(query=bad):
                with self.assertRaises(ValueError):
                    self.r.retrieve(RetrieveRequest(query=bad))

    def test_invalid_top_k(self):
        for bad in (0, -1, "5", 2.5, True):
            with self.subTest(top_k=bad):
                with self.assertRaises(ValueError):
                    self.r.retrieve(RetrieveRequest(query="Python", top_k=bad))

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            self.r.retrieve(RetrieveRequest(query="Python", mode="nonsense"))

    def test_unknown_company_raises(self):
        with self.assertRaises(ValueError):
            self.r.retrieve(RetrieveRequest(query="Python", company="不存在的公司"))

    def test_blank_company_is_ignored(self):
        result = self.r.retrieve(RetrieveRequest(query="Python", company="   "))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertIsNone(result.company_slug)

    def test_result_to_dict_shape(self):
        d = self.r.retrieve(RetrieveRequest(query="恒生电子 Python")).to_dict()
        for key in ("status", "mode", "company_slug", "company_name", "query", "evidence", "diagnostics"):
            self.assertIn(key, d)


# ── 9. 不触碰真实索引 ───────────────────────────────────────────────────
class TestRealIndexSafety(unittest.TestCase):
    INDEX_DIR = REPO_ROOT / "knowledge" / "index"

    def _snapshot(self):
        if not self.INDEX_DIR.exists():
            return None
        return sorted((str(p.relative_to(self.INDEX_DIR)), p.stat().st_size) for p in self.INDEX_DIR.rglob("*") if p.is_file())

    def test_default_backend_is_lazy_and_readonly(self):
        store = ChromaVectorStore(index_dir=self.INDEX_DIR)
        self.assertIsNone(store._store, "构造时不应创建 Chroma 客户端")

    def test_missing_index_raises_without_connecting(self):
        store = ChromaVectorStore(index_dir=REPO_ROOT / "knowledge" / "__no_such_index__")
        with self.assertRaises(FileNotFoundError):
            store.all_records()
        self.assertIsNone(store._store)

    def test_real_index_is_untouched_by_test_run(self):
        before = self._snapshot()
        if before is None:
            self.skipTest("真实索引不存在，跳过")
        r, _ = make_retriever()
        r.retrieve(RetrieveRequest(query="恒生电子 Python"))
        r.retrieve(RetrieveRequest(query="恒生电子要求 Docker 吗"))
        r.retrieve(RetrieveRequest(query="恒生电子 vs 易思维"))
        self.assertEqual(before, self._snapshot(), "测试运行改变了真实索引目录")

    def test_retriever_constructible_without_ollama(self):
        """默认构造会读 YAML，但不连接 Ollama/Chroma。"""
        r = JobKnowledgeRetriever()
        self.assertEqual(len(r._vocab.names), 18)


# ── 10. D1 无证据判定：不得把"向量有返回"当成"资料里有" ───────────────
class TestNoEvidenceJudgment(unittest.TestCase):
    """`terms=[]` 时，不能再因为向量检索返回了 Top-K 就判 matched。"""

    def setUp(self):
        self.r, self.store = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)

    def test_unknown_topic_is_not_mentioned(self):
        """资料里完全没有的主题（量子计算）不得返回无关证据并判 matched。"""
        result = self.r.retrieve(RetrieveRequest(query="这些岗位有没有明确要求量子计算？"))
        self.assertEqual(result.status, STATUS_NOT_MENTIONED)
        self.assertEqual(result.evidence, [])
        self.assertEqual(result.diagnostics["match_kind"], "term_scan")
        self.assertIn("量子计算", result.diagnostics["unmatched_content_terms"])
        self.assertIn("reason", result.diagnostics)

    def test_unknown_tech_terms_are_not_mentioned(self):
        """恒生电子没有 Vue / TypeScript，不得用无关技能冒充答案。"""
        result = self.r.retrieve(RetrieveRequest(query="恒生电子岗位对 Vue 或 TypeScript 有什么要求？"))
        self.assertEqual(result.status, STATUS_NOT_MENTIONED)
        self.assertEqual(result.evidence, [])
        self.assertEqual(result.company_slug, "hundsun")
        self.assertTrue({"vue", "typescript"} <= set(result.diagnostics["unmatched_content_terms"]))

    def test_unrelated_candidates_are_diagnostics_only(self):
        """未提及时不返回证据，向量候选只能出现在 diagnostics 里。"""
        result = self.r.retrieve(RetrieveRequest(query="恒生电子岗位对 Vue 或 TypeScript 有什么要求？"))
        self.assertEqual(result.evidence, [])
        self.assertTrue(result.diagnostics["vector_candidates"])
        # 候选全部来自恒生电子，没有把别家公司的记录拿来顶替
        self.assertEqual(
            {c["company_slug"] for c in result.diagnostics["vector_candidates"]}, {"hundsun"}
        )

    def test_no_cross_company_substitution(self):
        """众智诚坚确有 Vue 记录，但问恒生电子时仍必须是 not_mentioned。"""
        self.assertIn("Vue", {r["skill"] for r in EXTRA_RECORDS if r["company_slug"] == "zhongzhi"})
        result = self.r.retrieve(RetrieveRequest(query="恒生电子岗位对 Vue 有什么要求？"))
        self.assertEqual(result.status, STATUS_NOT_MENTIONED)
        self.assertEqual(result.evidence, [])
        self.assertNotIn("zhongzhi", {c["company_slug"] for c in result.diagnostics["vector_candidates"]})

    def test_known_topic_is_not_swallowed_by_the_new_rule(self):
        """反例保护：资料里确实有的主题，不得被误判为 not_mentioned。"""
        result = self.r.retrieve(RetrieveRequest(query="有没有需要做文档处理的要求？"))
        self.assertNotEqual(result.status, STATUS_NOT_MENTIONED)
        self.assertTrue(result.diagnostics["matched_content_terms"])

    def test_content_terms_helper(self):
        self.assertEqual(extract_content_terms("恒生电子要求什么"), [])
        self.assertIn("量子计算", extract_content_terms("这些岗位有没有明确要求量子计算？"))
        self.assertTrue({"vue", "typescript"} <= set(
            extract_content_terms("恒生电子岗位对 Vue 或 TypeScript 有什么要求？")
        ))


# ── 11. D2 技能别名 / 上位词 ────────────────────────────────────────────
class TestSkillAliases(unittest.TestCase):
    def test_framework_question_matches_langchain(self):
        """"Agent 开发框架"这类问法必须走确定性路径命中 LangChain / LangGraph。"""
        v = SkillVocabulary(skill_names=EXTRA_SKILLS)
        detailed = dict(v.match_detailed("众智诚坚提到了哪些 Agent 开发框架？"))
        self.assertEqual(detailed.get("LangChain / LangGraph"), "alias")
        self.assertEqual(detailed.get("Agent"), "literal")

    def test_mcp_question_matches_mcp_skill(self):
        v = SkillVocabulary(skill_names=EXTRA_SKILLS)
        self.assertEqual(v.match("众智诚坚对 MCP 有什么要求？"), ["Agent Skill / MCP 工具封装"])

    def test_framework_question_returns_langchain_evidence(self):
        r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)
        result = r.retrieve(RetrieveRequest(query="众智诚坚提到了哪些 Agent 开发框架？"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.diagnostics["match_kind"], "exact_skill")
        # 别名把"框架"这类问法引到了确定性路径上，框架证据必须出现
        self.assertIn("LangChain / LangGraph", {e["skill"] for e in result.evidence})
        self.assertIn("LangChain / LangGraph", result.diagnostics["alias_terms"])
        self.assertEqual(
            result.diagnostics["skill_term_origins"]["LangChain / LangGraph"], "alias"
        )
        # 但别名不再无条件排在最前：required 的 Agent 证据排在 bonus 的框架证据之前
        skills = [e["skill"] for e in result.evidence]
        first_framework = skills.index("LangChain / LangGraph")
        self.assertTrue(
            all(result.evidence[i]["requirement_type"] == "required" for i in range(first_framework)),
            f"别名证据压过了硬性要求：{[(e['skill'], e['requirement_type']) for e in result.evidence]}",
        )

    def test_mcp_question_returns_both_requirement_types(self):
        r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)
        result = r.retrieve(RetrieveRequest(query="众智诚坚对 MCP 有什么要求？"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.diagnostics["match_kind"], "exact_skill")
        self.assertEqual({e["skill"] for e in result.evidence}, {"Agent Skill / MCP 工具封装"})
        self.assertEqual({e["requirement_type"] for e in result.evidence}, {"required", "bonus"})

    def test_generic_word_does_not_trigger_alias(self):
        """防过度匹配：光说"框架"不映射到任何技能。"""
        v = SkillVocabulary(skill_names=EXTRA_SKILLS)
        self.assertEqual(v.match("有什么框架方面的要求"), [])

    def test_alias_disabled_when_target_skill_absent(self):
        """目标技能不在词表时别名失效，避免把查询引向不存在的技能。"""
        v = SkillVocabulary(skill_names=["Python"])
        self.assertEqual(v.match("众智诚坚对 MCP 有什么要求？"), [])
        v2 = SkillVocabulary(skill_names=["Python", "Agent Skill / MCP 工具封装"])
        self.assertEqual(v2.match("众智诚坚对 MCP 有什么要求？"), ["Agent Skill / MCP 工具封装"])

    def test_alias_targets_exist_in_real_profile(self):
        """别名表只能指向真实存在的技能名（读真实 YAML，不连 Ollama）。"""
        names = set(SkillVocabulary().names)
        self.assertEqual(set(SKILL_ALIASES) - names, set())


# ── 12. D3 同源重复：一句话不该占满 Top-K ───────────────────────────────
class TestSharedNoteCollapse(unittest.TestCase):
    def setUp(self):
        self.r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)

    def test_named_skills_keep_their_own_evidence(self):
        """被点名的技能必须留下可追溯证据，不能只写进 also_supports。"""
        result = self.r.retrieve(RetrieveRequest(query="众智诚坚要求 RAG 或 Agent 吗"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.diagnostics["evidence_skills"], ["Agent", "RAG"])
        for skill in ("RAG", "Agent"):
            with self.subTest(skill=skill):
                self.assertTrue(
                    [e for e in result.evidence if e["skill"] == skill],
                    f"{skill} 被点名却没有证据",
                )

    def test_shared_note_still_cross_referenced(self):
        """共享原文仍然互相登记在 also_supports 里，只是不再互相顶掉。"""
        result = self.r.retrieve(RetrieveRequest(query="众智诚坚要求 RAG 或 Agent 吗"))
        shared = [e for e in result.evidence if "任职要求4" in e["note"]]
        self.assertTrue(shared)
        for item in shared:
            self.assertIn("also_supports", item)
            self.assertTrue(set(item["also_supports"]) & {"RAG", "Agent", "Prompt Engineering"})

    def test_collapse_still_applies_to_unnamed_skills(self):
        """没被点名的技能（语义检索路径）仍按同源原文合并，避免重复占位。"""
        result = self.r.retrieve(RetrieveRequest(query="有没有需要做文档处理的要求？"))
        notes = [e["note"] for e in result.evidence]
        self.assertEqual(len(notes), len(set(notes)))

    def test_different_requirement_types_are_not_merged(self):
        """同一技能的 required 与 bonus 是两条不同原文，必须都保留。"""
        result = self.r.retrieve(RetrieveRequest(query="众智诚坚对 MCP 有什么要求？"))
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual({e["requirement_type"] for e in result.evidence}, {"required", "bonus"})

    def test_collapse_frees_slots_in_vector_path(self):
        """向量路径下先合并同源再截断，覆盖度应高于"直接取 Top-5"的结果。"""
        result = self.r.retrieve(RetrieveRequest(query="有没有需要做文档处理的要求？"))
        self.assertEqual(result.diagnostics["match_kind"], "vector_only")
        notes = [e["note"] for e in result.evidence]
        self.assertEqual(len(notes), len(set(notes)))
        self.assertGreater(len({e["skill"] for e in result.evidence}), 1)


# ── 13. D4 整体性问题：按技能聚合，而不是向量 Top-K ─────────────────────
class TestOverviewStrategy(unittest.TestCase):
    def setUp(self):
        self.r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)

    def test_company_overview_has_no_duplicate_sentences(self):
        """单公司整体性问题：同一句原文的多个切片不得占前三名。"""
        result = self.r.retrieve(RetrieveRequest(query="众智诚坚这个岗位到底要什么？"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.diagnostics["match_kind"], "overview")
        self.assertEqual(result.company_slug, "zhongzhi")
        notes = [e["note"] for e in result.evidence]
        self.assertEqual(len(notes), len(set(notes)))
        self.assertGreater(len({e["skill"] for e in result.evidence}), 1)
        self.assertEqual(result.diagnostics["scope_count"], count_records("zhongzhi"))

    def test_job_family_overview_is_cross_company(self):
        """不指定公司时按跨公司覆盖度聚合，并保留公司来源。"""
        result = self.r.retrieve(
            RetrieveRequest(query="不指定公司时，AI 应用开发岗位通常要求哪些技能？", mode=MODE_FAMILY)
        )
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.diagnostics["match_kind"], "overview")
        self.assertIsNone(result.company_slug)
        self.assertGreaterEqual(len({e["company_slug"] for e in result.evidence}), 2)
        for item in result.evidence:
            self.assertIn("companies", item)
            self.assertIn("requirement_types", item)
            self.assertEqual(item["jd_count"], len(result.diagnostics["sources_included"]))
        top = result.diagnostics["skill_summary"][0]
        self.assertGreaterEqual(len(top["companies"]), 2)

    def test_overview_detected_without_marker_phrase(self):
        """"…一般要会什么"没有踩中任何固定短语，也要能进 overview（判据是内容词收敛度）。"""
        result = self.r.retrieve(RetrieveRequest(query="AI 应用开发工程师一般要会什么"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.diagnostics["match_kind"], "overview")
        self.assertTrue(result.evidence)
        self.assertIn("skill_summary", result.diagnostics)

    def test_overview_states_sample_scope(self):
        """概览结果必须写明样本范围，不能把 3 家公司说成整个行业。"""
        result = self.r.retrieve(
            RetrieveRequest(query="不指定公司时，AI 应用开发岗位通常要求哪些技能？", mode=MODE_FAMILY)
        )
        self.assertEqual(result.diagnostics["match_kind"], "overview")
        scope = result.diagnostics["sample_scope"]
        jd_count = len(result.diagnostics["sources_included"])
        self.assertEqual(scope["jd_count"], jd_count)
        self.assertEqual(scope["sources"], result.diagnostics["sources_included"])
        self.assertTrue(scope["companies"])
        self.assertIn("行业", scope["caveat"])
        self.assertIn(str(jd_count), scope["caveat"])
        for item in result.evidence:
            self.assertEqual(item["jd_count"], jd_count)

    def test_overview_preserves_requirement_type(self):
        result = self.r.retrieve(RetrieveRequest(query="这个岗位到底要什么"))
        self.assertTrue(result.evidence)
        for item in result.evidence:
            self.assertIn(item["requirement_type"], ("required", "preferred", "bonus"))

    def test_overview_respects_top_k(self):
        result = self.r.retrieve(RetrieveRequest(query="这个岗位到底要什么", top_k=2))
        self.assertLessEqual(len(result.evidence), 2)

    def test_overview_evidence_is_not_marked_as_vector(self):
        result = self.r.retrieve(RetrieveRequest(query="这个岗位到底要什么"))
        self.assertEqual({e["origin"] for e in result.evidence}, {"overview"})


# ── 14. F1 点名了的技能不得因共享原文而丢证据 ───────────────────────────
class TestNamedSkillCoverage(unittest.TestCase):
    """共享同一句原文时，被查询点名的技能必须各自留下可追溯证据。"""

    def setUp(self):
        self.r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)

    def test_two_skills_sharing_one_sentence_both_keep_evidence(self):
        """计算机网络与操作系统共享"岗位要求3"，两者都必须有证据。"""
        result = self.r.retrieve(RetrieveRequest(query="恒生电子对计算机网络和操作系统有什么要求？"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(
            set(result.diagnostics["evidence_skills"]), {"计算机网络", "操作系统"}
        )
        for skill in ("计算机网络", "操作系统"):
            with self.subTest(skill=skill):
                hits = [e for e in result.evidence if e["skill"] == skill]
                self.assertTrue(hits, f"{skill} 被点名却没有证据")
                self.assertTrue(all(e["note"] for e in hits))
        # 同一句原文：两个技能各持一条，且都登记了对方
        self.assertEqual({e["note"] for e in result.evidence}, {
            next(e["note"] for e in result.evidence)
        })
        for item in result.evidence:
            self.assertEqual(
                set(item["also_supports"]), {"计算机网络", "操作系统"} - {item["skill"]}
            )

    def test_alias_and_literal_skills_sharing_one_sentence(self):
        """别名命中的技能不能吃掉字面命中技能的唯一证据。"""
        result = self.r.retrieve(RetrieveRequest(query="众智诚坚对提示词和 Embedding 有什么要求？"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertTrue(
            {"Embedding", "Prompt Engineering"} <= set(result.diagnostics["evidence_skills"])
        )
        self.assertTrue([e for e in result.evidence if e["skill"] == "Embedding"])

    def test_coverage_keeps_requirement_type_distinct(self):
        result = self.r.retrieve(RetrieveRequest(query="众智诚坚对 MCP 有什么要求？"))
        self.assertEqual({e["requirement_type"] for e in result.evidence}, {"required", "bonus"})

    def test_every_named_skill_has_evidence(self):
        """一次点名三个技能，逐个核对，不允许任何一个静默消失。"""
        result = self.r.retrieve(
            RetrieveRequest(query="恒生电子对 Python、计算机网络和操作系统有什么要求？")
        )
        self.assertTrue(
            {"Python", "计算机网络", "操作系统"} <= set(result.diagnostics["evidence_skills"])
        )


# ── 15. F2 别名精度：后端侧说法 vs Agent/RAG 侧说法 ─────────────────────
class TestAliasPrecision(unittest.TestCase):
    def test_backend_framework_does_not_map_to_langchain(self):
        v = SkillVocabulary(skill_names=EXTRA_SKILLS)
        matched = v.match("有没有要求后端开发框架经验")
        self.assertIn("后端 API 开发", matched)
        self.assertNotIn("LangChain / LangGraph", matched)

    def test_agent_framework_still_maps_to_langchain(self):
        v = SkillVocabulary(skill_names=EXTRA_SKILLS)
        for query in ("众智诚坚提到了哪些 Agent 开发框架？", "有没有要求智能体框架",
                      "大模型开发框架有要求吗", "做过 agent 框架吗"):
            with self.subTest(query=query):
                self.assertIn("LangChain / LangGraph", v.match(query))

    def test_bare_framework_word_maps_to_nothing(self):
        v = SkillVocabulary(skill_names=EXTRA_SKILLS)
        self.assertEqual(v.match("有什么框架方面的要求"), [])

    def test_backend_framework_query_end_to_end(self):
        r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)
        result = r.retrieve(RetrieveRequest(query="恒生电子有没有要求后端开发框架经验？"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual({e["skill"] for e in result.evidence}, {"后端 API 开发"})
        self.assertEqual({e["requirement_type"] for e in result.evidence}, {"preferred"})
        self.assertEqual({e["company_slug"] for e in result.evidence}, {"hundsun"})

    def test_agent_framework_query_end_to_end(self):
        r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)
        result = r.retrieve(RetrieveRequest(query="众智诚坚提到了哪些 Agent 开发框架？"))
        self.assertIn("LangChain / LangGraph", {e["skill"] for e in result.evidence})


# ── 16. F3 排序：别名不能无条件压过 origin / 要求性质 / 重要性 ───────────
class TestEvidenceOrdering(unittest.TestCase):
    def setUp(self):
        self.r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)

    def test_required_evidence_precedes_alias_matched_preferred(self):
        """required 的 Python 不得因为框架证据触发别名而被挤到后面。"""
        result = self.r.retrieve(
            RetrieveRequest(query="恒生电子对 Python 和智能体框架有什么要求？")
        )
        self.assertEqual(result.status, STATUS_MATCHED)
        skills = [e["skill"] for e in result.evidence]
        self.assertIn("Python", skills)
        self.assertIn("LangChain / LangGraph", skills)
        first_framework = skills.index("LangChain / LangGraph")
        self.assertTrue(first_framework > 0, "别名证据排到了最前")
        self.assertEqual(
            {e["skill"] for e in result.evidence[:first_framework]}, {"Python"}
        )
        for item in result.evidence[:first_framework]:
            self.assertEqual(item["requirement_type"], "required")

    def test_alias_does_not_beat_requirement_strength_at_same_origin(self):
        """固定候选集：别名命中 + 距离更近，也不能把 required 挤掉。"""
        recs = [
            record("Python", "hundsun", H, "岗位要求2「熟练掌握Python或Java任一语言」", importance=5),
            record("LangChain / LangGraph", "hundsun", H,
                   "岗位要求9「有Hugging Face、LangChain等大模型开发工具使用经验…者优先」",
                   rt="preferred", importance=3),
        ]
        # 框架那条距离更近（0.10），且是别名命中 —— 两者都不足以让它排在 required 之前
        plan = [(recs[1], 0.10), (recs[0], 0.90)]
        r, _ = make_retriever(records=recs, skills=["Python", "LangChain / LangGraph"],
                              search_plan=plan)
        result = r.retrieve(RetrieveRequest(query="恒生电子对 Python 和智能体框架有什么要求？"))
        self.assertEqual(result.evidence[0]["skill"], "Python")
        self.assertEqual(result.evidence[0]["requirement_type"], "required")
        self.assertAlmostEqual(result.evidence[0]["distance"], 0.90)
        self.assertEqual(result.evidence[-1]["skill"], "LangChain / LangGraph")

    def test_ordering_does_not_rewrite_requirement_type(self):
        """排序调整不得顺手改写要求性质。"""
        result = self.r.retrieve(
            RetrieveRequest(query="恒生电子对 Python 和智能体框架有什么要求？")
        )
        types = {e["skill"]: e["requirement_type"] for e in result.evidence}
        self.assertEqual(types["Python"], "required")
        self.assertEqual(types["LangChain / LangGraph"], "preferred")


# ── 17. F4/F5 内容单元判定与别名表口径一致 ──────────────────────────────
class TestContentUnitVocabulary(unittest.TestCase):
    def setUp(self):
        self.r, _ = make_retriever(records=EXTRA_RECORDS, skills=EXTRA_SKILLS)

    def test_container_wording_resolves_to_docker(self):
        result = self.r.retrieve(RetrieveRequest(query="有没有要求掌握容器相关技术？"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual({e["skill"] for e in result.evidence}, {"Docker"})
        self.assertEqual(result.diagnostics["alias_terms"], ["Docker"])

    def test_vector_db_wording_resolves_to_embedding(self):
        result = self.r.retrieve(RetrieveRequest(query="有没有要求做过向量数据库？"))
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual({e["skill"] for e in result.evidence}, {"Embedding"})

    def test_no_defensible_alias_stays_conservative(self):
        """没有可辩护的上位词时保守判未提及，不拿无关向量结果当证据。"""
        result = self.r.retrieve(RetrieveRequest(query="有没有要求模型部署上线"))
        self.assertEqual(result.status, STATUS_NOT_MENTIONED)
        self.assertEqual(result.evidence, [])
        self.assertEqual(result.diagnostics["match_kind"], "term_scan")
        self.assertTrue(result.diagnostics["unmatched_content_units"])

    def test_generic_word_does_not_rescue_a_missing_topic(self):
        """"AI"命中不能抵消"量子计算经验"整个单元完全未命中。"""
        result = self.r.retrieve(RetrieveRequest(query="这些岗位有没有要求 AI 量子计算经验？"))
        self.assertEqual(result.status, STATUS_NOT_MENTIONED)
        self.assertEqual(result.evidence, [])
        self.assertIn("量子计算经验", result.diagnostics["unmatched_content_units"])
        self.assertIn("ai", result.diagnostics["matched_content_terms"])

    def test_generic_word_alone_still_answers(self):
        """反例保护：只有通用词、但资料里确实有时，不得判成未提及。"""
        result = self.r.retrieve(RetrieveRequest(query="有没有要求 AI 相关能力？"))
        self.assertNotEqual(result.status, STATUS_NOT_MENTIONED)

    def test_conjunctions_split_units(self):
        self.assertEqual([u.text for u in extract_content_units("日志和监控")], ["日志", "监控"])
        self.assertEqual([u.text for u in extract_content_units("容器或向量数据库")],
                         ["容器", "向量数据库"])

    def test_alias_words_are_shared_between_both_mechanisms(self):
        """别名表就是内容单元判定用的词表 —— 两处不能各有一套说法。"""
        v = SkillVocabulary(skill_names=EXTRA_SKILLS)
        for word in ("容器", "向量数据库", "mcp", "智能体框架"):
            with self.subTest(word=word):
                self.assertIn(word, [w for ws in v.aliases.values() for w in ws])


if __name__ == "__main__":
    unittest.main(verbosity=2)
