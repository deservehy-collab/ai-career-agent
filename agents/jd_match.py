"""阶段四：真实 JD 定向匹配（确定性汇总 + 只读元数据）。

本模块是**纯计算的汇总层**，用于在既有 RAG 岗位知识库 / 证据引用闭环之上，
把"某一份真实 JD（或某家公司）作为匹配目标"的结果整理出来：

- `load_jd_metadata()`：只读扫描 `knowledge/jd/*/*.md` 的 YAML front matter，
  返回 ``{source_id: {...}}``。不修改原始 JD 数据，不触碰 Chroma。
- `resolve_target()`：把入口参数（``jd_source_id`` / ``target_company``）解析成
  单一匹配目标。两者都传时校验一致性，不一致**明确报错**，绝不静默二选一。
- `compute_jd_match()`：**纯函数**，不连 Ollama / Chroma，不做 IO，只依据传入的
  ``skill_gaps`` + ``job_requirements`` + ``job_evidence`` 做确定性统计。

判定口径（来自阶段四验收要求，代码逐条落实）：
1. 只统计目标 JD 的证据，不得混入其他公司证据（attribution 按 ``source_id`` 判定，
   ``source_companies`` 只是辅助展示，不单独用来认定归属）。
2. 归属判据是**代码回查**：要求的 ``evidence_refs`` 能不能在 ``job_evidence`` 里按编号
   找到真实记录。**不采信模型自填的 ``evidence_status``** —— 模型说"有证据"不算数。
   回查不到的要求不计入任何一项统计。
3. 没有可判定要求时 ``overall`` 直接返回 ``insufficient``，不强行出满足率。
4. ``overall`` 只使用 confirmed 的规则：全满足且无未解决硬性缺口 → ``satisfied``；
   存在明确差距 → ``partial``；证据不足 → ``insufficient``。不加未经确认的阈值。
5. 来源可信度提示只依据 ``status`` / ``source`` / ``url`` / ``company`` 这些**可核验字段**，
   不根据 ``origin`` 推断"是否企业官网一手信息"——``origin`` 在本项目里记录的是
   **数据来源方式**（JD 原文 ``jd_raw`` / 画像人工整理 ``human``），与"官网 vs 非官网"
   是两回事。识别不出招聘方自身域名时一律保守标注为第三方/待核实。

计数口径（五个数含义不同，不得混用）
------------------------------------
==========================  ==================================================
``requirement_total``       **有证据归属**的要求数（≠ 可判定数，其中可能还有
                            对不上能力差距的项）
``requirement_judged``      **可判定**要求数 = 已满足 + 存在差距，**满足率的分母**
``requirement_satisfied``   已满足数
``requirement_shortfall``   存在差距数
``requirement_orphan``      证据不足数 = total - judged（不进分子也不进分母）
==========================  ==================================================

满足率 ``match_rate`` 的分母**只能是** ``requirement_judged``；它为 0 时取 ``None``，
调用方必须不显示百分比，也不得拿 ``requirement_total`` 当分母。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from agents.retriever import resolve_company

REPO_ROOT = Path(__file__).resolve().parent.parent
JD_GLOB = "knowledge/jd/*/*.md"

# 参与匹配展示的 JD 元信息字段（只读透出，写死这些字段，不擅自扩展）
JD_META_FIELDS = (
    "source_id",
    "company_slug",
    "job_name",
    "company",
    "city",
    "salary",
    "education",
    "published_at",
    "status",
    "origin",
    "source",
    "url",
)

# 未解决硬性缺口的门槛：目标要求有证据支撑 + 当前能力为"无" + 等级重要。
# importance 沿用岗位画像的 1~5 人工评级（画像约定 importance=3 不得被当作硬性要求）。
_HARD_IMPORTANCE = 4

_PRIORITY_RANK = {"高": 0, "中": 1, "低": 2}
_GAP_SHORTFALL = ("部分满足", "明显不足")

# 有证据支撑的 evidence_status：
#   supported           —— 技能名与证据完全同名
#   partially_supported —— 仅靠别名/语义相关，证据强度弱于 supported
# 两者都参与硬性缺口判定（规则不变），但条目里会原样带出 ``evidence_status``，
# 供调用方区分"完全确认"与"仅弱证据"，不得把后者描述成完全确认。
_EVIDENCE_BACKED_STATUSES = ("supported", "partially_supported")


def load_jd_metadata() -> dict[str, dict]:
    """只读扫描 JD Markdown，按 source_id 索引其 YAML front matter（无写操作）。

    只挑选 `JD_META_FIELDS` 列出的标量字段；缺字段的按 None 处理，
    不因某份 JD 字段不全而中止匹配。
    """
    result: dict[str, dict] = {}
    jd_dir = REPO_ROOT / "knowledge" / "jd"
    # JD 原文放在 knowledge/jd/<采集批次>/xxxx.md，递归扫描（只读）。
    for md in sorted(jd_dir.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not match:
            continue
        front = yaml.safe_load(match.group(1)) or {}
        source_id = front.get("source_id")
        if not source_id:
            continue
        result[str(source_id)] = {
            key: front.get(key) for key in JD_META_FIELDS
        }
    return result


def _require_company_slug(source_id: str, meta: dict) -> str:
    """取这份 JD 的 company_slug；缺了就报错，绝不退化成跨公司检索。

    缺 ``company_slug`` 时无法把检索限定在某一家公司，会从"单份 JD 匹配"扩大成
    "全库匹配"——这是安全边界，必须失败而不是降级。
    """
    slug = str(meta.get("company_slug") or "").strip()
    if not slug:
        raise ValueError(
            f"JD {source_id!r} 的 front matter 缺少 company_slug，无法确认归属公司；"
            f"为避免退化成跨公司检索，已拒绝按该 JD 匹配"
        )
    return slug


def resolve_target(
    jd_source_id, target_company, metadata: dict | None = None,
) -> dict:
    """把入口参数解析成单一匹配目标。

    返回 ``{source_id, company_slug, jd_meta}``：
    - 只传 ``jd_source_id`` → 精确匹配该 JD（优先级最高）；
    - 只传 ``target_company`` → 公司级匹配，``source_id`` 为 None；
    - 两者都传 → 校验该公司与该 JD 是否一致，**不一致明确报错**；
    - 都不传 → 跨公司概览，``source_id``/``company_slug`` 均为 None。

    无法解析（source_id 不存在、公司名无法识别、JD 缺 company_slug）一律抛
    ``ValueError``。由调用方决定是明确报错还是降级 ——
    ``retrieval_agent`` 只对"单独传入的 target_company 无法识别"这一种情况降级
    （阶段二既有行为），其余一律明确报错。
    """
    metadata = metadata if metadata is not None else load_jd_metadata()

    first = str(jd_source_id or "").strip()
    second = str(target_company or "").strip()

    if first and second:
        if first not in metadata:
            raise ValueError(f"无法识别的 jd_source_id：{first!r}")
        meta = metadata[first]
        slug = _require_company_slug(first, meta)
        resolved = resolve_company(second)
        if resolved is None:
            raise ValueError(f"无法识别的 target_company：{second!r}")
        if slug != resolved:
            raise ValueError(
                f"jd_source_id（{first!r}，公司 {slug!r}）"
                f"与 target_company（{second!r}，解析为 {resolved!r}）不一致"
            )
        return {
            "source_id": first,
            "company_slug": slug,
            "jd_meta": meta,
        }

    if first:
        if first not in metadata:
            raise ValueError(f"无法识别的 jd_source_id：{first!r}")
        meta = metadata[first]
        return {
            "source_id": first,
            "company_slug": _require_company_slug(first, meta),
            "jd_meta": meta,
        }

    if second:
        resolved = resolve_company(second)
        if resolved is None:
            raise ValueError(f"无法识别的 target_company：{second!r}")
        return {
            "source_id": None,
            "company_slug": resolved,
            "jd_meta": None,
        }

    return {"source_id": None, "company_slug": None, "jd_meta": None}


def _norm_skill(name) -> str:
    return str(name or "").strip().lower().replace(" ", "")


def _req_evidence(req: dict, evidence: list) -> list[dict]:
    """取一条岗位要求实际引用的证据记录（按 evidence_refs 里的编号）。

    ``evidence_refs`` 形如 ["E01"]，E01 对应 ``job_evidence[0]``。
    只做只读回查，回查不到就忽略，绝不采信模型填写的其他文本。
    """
    refs = req.get("evidence_refs") or []
    picked: list[dict] = []
    for ref in refs:
        m = re.fullmatch(r"E(\d+)", str(ref or "").strip())
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(evidence):
            picked.append(evidence[idx])
    return picked


def _attached_to_target(req: dict, evidence: list, jd_target: str | None,
                        company_slug: str | None) -> bool:
    """判断这条岗位要求是否归属目标 JD / 目标公司。

    归属以 **source_id** 为准：证据不足的（evidence_refs 回查不到）一律不算
    （口径 2）。据此：
    - 指定 ``jd_target``：要求引用的证据里只要有一个属于该 JD 即归属；
    - 仅公司级（``company_slug`` 而非单 JD）：要求引用证据的公司与目标公司一致即归属；
    - 跨公司概览：有真实证据即归属（否则无法计数）。
    """
    picked = _req_evidence(req, evidence)
    if not picked:
        return False
    if jd_target:
        return any(item.get("source_id") == jd_target for item in picked)
    if company_slug:
        return any(item.get("company_slug") == company_slug for item in picked)
    return True


def _url_host(url) -> str | None:
    """取 URL 的主机名（小写、去掉 ``www.``）；取不到返回 None。"""
    text = str(url or "").strip()
    if not text:
        return None
    try:
        host = urlsplit(text).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _source_is_verifiable(jd_meta: dict, host: str | None) -> bool:
    """能否确认这份 JD 来自招聘方自己的域名。

    只做**能确证**的判断：URL 主机名里出现这家公司自己的标识（``company_slug``）时，
    才认为来源可能就是招聘方。本项目**不维护官方域名白名单**，也不从公司中文名
    猜拼音域名 —— 没有可核验依据时一律返回 False，由调用方保守标注"待核实"，
    绝不凭空断言某条来源是或不是企业官网。
    """
    if not host:
        return False
    slug = str(jd_meta.get("company_slug") or "").strip().lower()
    return bool(slug) and slug in host


def _jd_warning(jd_meta: dict | None, company_slug: str | None) -> list[str]:
    """依据可核验的来源字段生成可信度提示（口径 5）。

    三种情况分开说，不混用文案：
    - 有 ``jd_meta``：针对这一份 JD 的来源可信度；
    - 只有 ``company_slug``：公司级匹配（**不是**跨公司概览）；
    - 两者都没有：跨公司概览。

    只使用 ``status`` / ``source`` / ``url`` / ``company``；**不使用 ``origin``**
    推断"是否企业官网一手信息"。
    """
    if jd_meta is not None:
        warnings: list[str] = []
        status = str(jd_meta.get("status") or "").strip()
        if "待核实" in status:
            warnings.append(
                f"该 JD 来源状态为「{status}」，招聘信息未经最终确认，"
                f"请以招聘方最新发布为准。"
            )

        host = _url_host(jd_meta.get("url"))
        source = str(jd_meta.get("source") or "").strip()
        if not host and not source:
            warnings.append("该 JD 未提供来源链接与来源说明，来源无法核实。")
        elif not _source_is_verifiable(jd_meta, host):
            where = f"来源：{source}" if source else "来源未说明"
            link = host if host else "未提供链接"
            warnings.append(
                f"该 JD 采集自第三方渠道（{where}；{link}），"
                f"无法确认是招聘方官方发布，请以官网核实为准。"
            )
        return warnings

    if company_slug:
        return [
            f"当前为公司级匹配（{company_slug}），未指定单一真实 JD；"
            f"以上结论基于该公司的现有岗位样本，不代表该公司任何单一岗位的门槛。"
        ]
    return [
        "当前为跨公司概览匹配，未指定单一真实 JD；"
        "以上结论基于现有岗位样本，不代表任何单一公司门槛。"
    ]


def compute_jd_match(
    skill_gaps: list,
    job_requirements: list,
    evidence: list,
    jd_meta: dict | None = None,
    jd_target: str | None = None,
    company_slug: str | None = None,
) -> dict:
    """确定性汇总：对（目标 JD / 公司）产出匹配结论。纯函数，无 IO。

    参数：
    - ``skill_gaps``    来自 Assessment Agent（含 status / current_level / priority）
    - ``job_requirements``  来自 Job Agent（含 evidence_refs / evidence_status / importance）
    - ``evidence``      来自 Retrieval Agent 的 ``job_evidence``（含 source_id / company_slug）
    - ``jd_meta``       目标 JD 的元信息（load_jd_metadata 的单条）
    - ``jd_target``     目标 source_id；None 表示公司级或跨公司概览
    - ``company_slug``  目标公司 slug；None 表示跨公司概览

    返回的五个计数含义见模块 docstring 的"计数口径"表。
    """
    skill_gaps = list(skill_gaps or [])
    job_requirements = list(job_requirements or [])
    evidence = list(evidence or [])

    # 1) 归属目标的要求，去重（口径：同技能只计一次）
    seen: set[str] = set()
    attached: list[dict] = []
    for req in job_requirements:
        if not _attached_to_target(req, evidence, jd_target, company_slug):
            continue
        key = _norm_skill(req.get("skill"))
        if key in seen:
            continue
        seen.add(key)
        attached.append(req)

    # requirement_total = **有证据归属**的要求数（不是可判定数，也不是全部要求数）
    requirement_total = len(attached)

    # 2) 与 skill_gaps 按技能名对号，统计满足 / 缺口
    gap_by_skill = {_norm_skill(g.get("skill")): g for g in skill_gaps}
    satisfied: list[dict] = []
    shortfall: list[dict] = []
    hard_blocks: list[dict] = []
    for req in attached:
        gap = gap_by_skill.get(_norm_skill(req.get("skill")))
        if gap is None:
            continue  # assessment 未给出该项，按证据不足处理，不计入
        status = gap.get("status")
        if status == "已满足":
            satisfied.append(gap)
        elif status in _GAP_SHORTFALL:
            shortfall.append(gap)
        # 硬性缺口：目标要求有证据支撑 + 当前为"无" + 重要（规则与阶段四一致，
        # 只是把 evidence_status 一并带出去，让 supported / partially_supported 可区分）
        if (
            gap.get("current_level") == "无"
            and req.get("evidence_status") in _EVIDENCE_BACKED_STATUSES
            and int(req.get("importance") or 0) >= _HARD_IMPORTANCE
        ):
            hard_blocks.append({
                "skill": req.get("skill"),
                "required_level": gap.get("required_level"),
                "importance": req.get("importance"),
                "status": gap.get("status"),
                "evidence_status": req.get("evidence_status"),
            })

    requirement_satisfied = len(satisfied)
    requirement_shortfall = len(shortfall)
    # 可判定数 = 真正能参与比较的要求数；它才是满足率的分母
    requirement_judged = requirement_satisfied + requirement_shortfall
    # 证据不足数：有归属但对不上能力差距，既不进分子也不进分母
    requirement_orphan = requirement_total - requirement_judged
    # 分母为 0 时不出比率（口径 3）
    match_rate = (
        round(requirement_satisfied / requirement_judged, 4)
        if requirement_judged
        else None
    )

    # 3) matched_jd_count：实际参与匹配的来源 JD 数（以走证据为准）
    matched_sources = sorted({
        item.get("source_id")
        for item in evidence
        if item.get("source_id")
        and (jd_target is None or item.get("source_id") == jd_target)
        and (company_slug is None or item.get("company_slug") == company_slug)
    })
    matched_jd_count = len(matched_sources)

    # 4) overall（口径 3、4）+ key_gaps 复用 skill_gaps 排序
    if requirement_judged == 0:
        overall = "insufficient"
    elif requirement_shortfall > 0 or hard_blocks:
        overall = "partial"
    else:
        overall = "satisfied"

    target_list = [g for g in skill_gaps if _norm_skill(g.get("skill")) in seen]
    target_list.sort(key=lambda g: (_PRIORITY_RANK.get(g.get("priority"), 9), -int(g.get("importance") or 0), g.get("skill") or ""))

    return {
        "jd_target": jd_target,
        "matched_jd_count": matched_jd_count,
        "overall": overall,
        "requirement_total": requirement_total,
        "requirement_judged": requirement_judged,
        "requirement_orphan": requirement_orphan,
        "requirement_satisfied": requirement_satisfied,
        "requirement_shortfall": requirement_shortfall,
        "match_rate": match_rate,
        "hard_blocks": hard_blocks,
        "key_gaps": target_list,
        "jd_source_warning": _jd_warning(jd_meta, company_slug),
    }
