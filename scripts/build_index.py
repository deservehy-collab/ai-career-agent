"""从 knowledge/ 构建 Chroma 向量索引（岗位知识库）。

数据流：
    knowledge/jobs/*.yaml         岗位画像，skills[].evidence[] 是唯一的 evidence 来源
    knowledge/jd/<date>/*.md      三份 JD 摘要，提供 front matter 元数据（含 company_slug）
                ↓  每条 evidence 一个 chunk
    Chroma collection             共 45 条记录

用法：
    python scripts/build_index.py                          # 写入 knowledge/index/
    python scripts/build_index.py --index-dir <目录>        # 写入指定目录
    python scripts/build_index.py --dry-run                # 只校验和组装，不写索引

重建策略：默认先删除同名 collection 再重建，保证可重复执行且不会残留旧记录。
本脚本只操作 --index-dir 指定的目录，不触碰其他任何文件。
"""

import argparse
import re
import sys
from pathlib import Path

import yaml
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO_ROOT / "knowledge" / "jobs" / "ai-application-engineer.yaml"
JD_GLOB = "knowledge/jd/*/*.md"

EMBEDDING_MODEL = "nomic-embed-text:latest"
COLLECTION_NAME = "job_knowledge"

REQUIREMENT_TYPES = {"required", "preferred", "bonus"}
CONTEXTS = {"responsibility", "qualification", "bonus_section"}
LEVELS = {"入门", "初级", "中级", "高级"}
EVIDENCE_FIELDS = {"source_id", "requirement_type", "context", "note"}
SCALAR_TYPES = (str, int, float, bool)

EXPECTED_SKILLS = 18
EXPECTED_EVIDENCE = 45


class DataError(Exception):
    """知识库数据不符合预期时抛出，不做静默降级。"""


# ── 读取 ────────────────────────────────────────────────────────────────
def load_profile(path: Path) -> dict:
    if not path.exists():
        raise DataError(f"岗位画像文件不存在：{path}")
    with path.open(encoding="utf-8") as f:
        profile = yaml.safe_load(f)
    if not isinstance(profile, dict):
        raise DataError(f"岗位画像解析结果不是映射：{path}")
    return profile


def load_jd_metadata() -> dict:
    """扫描 knowledge/jd/ 下的 Markdown，按 source_id 索引其 YAML front matter。"""
    jd_dir = REPO_ROOT / "knowledge" / "jd"
    if not jd_dir.exists():
        raise DataError(f"JD 目录不存在：{jd_dir}")

    result = {}
    for md in sorted(REPO_ROOT.glob(JD_GLOB)):
        text = md.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not match:
            raise DataError(f"JD 文件缺少 YAML front matter：{md}")
        front = yaml.safe_load(match.group(1))
        source_id = front.get("source_id")
        if not source_id:
            raise DataError(f"JD front matter 缺少 source_id：{md}")
        if source_id in result:
            raise DataError(f"source_id 重复：{source_id}（{md} 与 {result[source_id]['_path']}）")
        front["_path"] = str(md.relative_to(REPO_ROOT))
        result[source_id] = front
    return result


# ── 校验 ────────────────────────────────────────────────────────────────
def validate(profile: dict, jd_meta: dict) -> None:
    skills = profile.get("skills")
    if not isinstance(skills, list):
        raise DataError("岗位画像缺少 skills 列表")

    if len(skills) != EXPECTED_SKILLS:
        raise DataError(f"技能数不符：期望 {EXPECTED_SKILLS}，实际 {len(skills)}")

    job_id = profile.get("job_id")
    if not job_id:
        raise DataError("岗位画像缺少 job_id")

    total = 0
    seen_skills = set()
    for skill in skills:
        name = skill.get("skill")
        if not name:
            raise DataError("存在没有 skill 名称的技能条目")
        if name in seen_skills:
            raise DataError(f"技能名称重复：{name}")
        seen_skills.add(name)

        if not isinstance(skill.get("importance"), int) or not 1 <= skill["importance"] <= 5:
            raise DataError(f"{name} 的 importance 非法：{skill.get('importance')!r}")
        if skill.get("level") not in LEVELS:
            raise DataError(f"{name} 的 level 非法：{skill.get('level')!r}")

        evidence = skill.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise DataError(f"{name} 缺少 evidence")

        for e in evidence:
            missing = EVIDENCE_FIELDS - set(e or {})
            if missing:
                raise DataError(f"{name} 的 evidence 缺少字段：{sorted(missing)}")
            if e["requirement_type"] not in REQUIREMENT_TYPES:
                raise DataError(f"{name} 的 requirement_type 非法：{e['requirement_type']!r}")
            if e["context"] not in CONTEXTS:
                raise DataError(f"{name} 的 context 非法：{e['context']!r}")
            if not str(e["note"]).strip():
                raise DataError(f"{name} 的 note 为空")
            if e["source_id"] not in jd_meta:
                raise DataError(
                    f"{name} 引用了不存在的 source_id：{e['source_id']!r}"
                    f"（可用：{sorted(jd_meta)}）"
                )
            total += 1

    if total != EXPECTED_EVIDENCE:
        raise DataError(f"evidence 总数不符：期望 {EXPECTED_EVIDENCE}，实际 {total}")

    # 每个 JD 都必须提供 company_slug，不允许根据公司名临时猜
    for source_id, front in jd_meta.items():
        slug = front.get("company_slug")
        if not slug or not str(slug).strip():
            raise DataError(f"{source_id} 的 front matter 缺少 company_slug")
        if front.get("job_id") != job_id:
            raise DataError(
                f"{source_id} 的 job_id（{front.get('job_id')!r}）与画像（{job_id!r}）不一致"
            )


# ── 组装 chunk ──────────────────────────────────────────────────────────
def build_chunks(profile: dict, jd_meta: dict) -> tuple[list[Document], list[str]]:
    """每条 evidence 一个 chunk。metadata 只放标量。"""
    job_id = profile["job_id"]
    job_name = profile["job_name"]

    documents, ids = [], []
    for skill in profile["skills"]:
        for e in skill["evidence"]:
            front = jd_meta[e["source_id"]]
            metadata = {
                "job_id": job_id,
                "source_id": e["source_id"],
                "company_slug": front["company_slug"],
                "skill": skill["skill"],
                "requirement_type": e["requirement_type"],
                "context": e["context"],
                "importance": skill["importance"],
                "level": skill["level"],
            }
            for key, value in metadata.items():
                if not isinstance(value, SCALAR_TYPES):
                    raise DataError(
                        f"metadata[{key}] 类型 {type(value).__name__} 不受 Chroma 支持"
                        f"（技能 {skill['skill']}）"
                    )

            text = (
                f"岗位：{job_name}\n"
                f"技能：{skill['skill']}\n"
                f"要求性质：{e['requirement_type']}\n"
                f"原文出处：{e['context']}\n"
                f"证据：{e['note']}"
            )
            documents.append(Document(page_content=text, metadata=metadata))
            ids.append(f"{job_id}::{e['source_id']}::{len(ids):03d}")

    return documents, ids


# ── 写索引 ──────────────────────────────────────────────────────────────
def build_index(documents: list[Document], ids: list[str], index_dir: Path, collection: str) -> Chroma:
    index_dir.mkdir(parents=True, exist_ok=True)

    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)

    # 重建策略：先删同名 collection，避免重复执行时旧记录残留
    store = Chroma(
        collection_name=collection,
        embedding_function=embeddings,
        persist_directory=str(index_dir),
    )
    try:
        store.delete_collection()
        print(f"  已清空同名 collection：{collection}")
    except Exception:
        print(f"  collection「{collection}」原本不存在，直接新建")
    store = Chroma(
        collection_name=collection,
        embedding_function=embeddings,
        persist_directory=str(index_dir),
    )

    store.add_documents(documents=documents, ids=ids)
    return store


# ── 入口 ────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 knowledge/ 构建 Chroma 岗位知识库索引（每条 evidence 一个 chunk）"
    )
    parser.add_argument(
        "--index-dir",
        default="knowledge/index",
        help="Chroma 持久化目录，默认 knowledge/index（相对项目根目录）",
    )
    parser.add_argument("--collection", default=COLLECTION_NAME, help="collection 名称")
    parser.add_argument("--dry-run", action="store_true", help="只校验与组装，不写入索引")
    args = parser.parse_args()

    index_dir = Path(args.index_dir)
    if not index_dir.is_absolute():
        index_dir = REPO_ROOT / index_dir

    print("读取知识库...")
    profile = load_profile(PROFILE_PATH)
    jd_meta = load_jd_metadata()
    print(f"  岗位画像：{PROFILE_PATH.relative_to(REPO_ROOT)}")
    print(f"  JD 来源  ：{len(jd_meta)} 份 -> {sorted(jd_meta)}")
    print(f"  索引目录 ：{index_dir}")

    print("校验数据...")
    validate(profile, jd_meta)
    print(f"  技能 {EXPECTED_SKILLS} 个 / evidence {EXPECTED_EVIDENCE} 条：通过")

    documents, ids = build_chunks(profile, jd_meta)
    print(f"组装 chunk：{len(documents)} 条")

    if args.dry_run:
        print("\n[dry-run] 未写入索引。示例 chunk：")
        print("-" * 60)
        print(documents[0].page_content)
        print("metadata:", documents[0].metadata)
        print("-" * 60)
        return 0

    print(f"写入索引（embedding 模型 {EMBEDDING_MODEL}）...")
    store = build_index(documents, ids, index_dir, args.collection)

    got = store.get()
    n = len(got["ids"])
    print(f"\n构建完成")
    print(f"  记录数  ：{n}")
    print(f"  索引路径：{index_dir}")
    print(f"  collection：{args.collection}")
    print("  各来源记录数：")
    for source_id in sorted(jd_meta):
        cnt = sum(1 for m in got["metadatas"] if m["source_id"] == source_id)
        print(f"    {source_id:18} {cnt} 条")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DataError as exc:
        print(f"\n[数据错误] {exc}", file=sys.stderr)
        sys.exit(2)
