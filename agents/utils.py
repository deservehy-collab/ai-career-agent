"""Agent 之间共用的小工具：技能等级归一化、列表去重、输出校验。

放在这里是为了避免每个 Agent 各写一份（小模型输出不稳定，兜底逻辑要统一）。
"""

SKILL_LEVELS = ("入门", "初级", "中级", "高级")

# 模型可能给出的各种等同说法，统一映射到四档
_LEVEL_SYNONYMS = {
    "入门": "入门",
    "初级": "初级",
    "中级": "中级",
    "高级": "高级",
    "了解": "入门",
    "听说过": "入门",
    "会用": "初级",
    "熟悉": "中级",
    "掌握": "中级",
    "熟练": "高级",
    "精通": "高级",
    "专家": "高级",
    "中等": "中级",
    "高": "高级",
    "中": "中级",
}


def normalize_level(value) -> str:
    """把模型输出的等级说法统一成 入门/初级/中级/高级 四档之一。

    无法识别时退回"初级"：比"入门"保守但不夸大，也不会让 pydantic 校验直接崩掉。
    """
    text = str(value or "").strip()
    if text in _LEVEL_SYNONYMS:
        return _LEVEL_SYNONYMS[text]

    # 含修饰语的说法，如 "比较熟练"、"中等偏上"
    if any(k in text for k in ("精通", "熟练", "高")):
        return "高级"
    if any(k in text for k in ("中", "熟悉", "掌握")):
        return "中级"
    if "初" in text:
        return "初级"
    if any(k in text for k in ("入门", "了解", "听说")):
        return "入门"
    return "初级"


def dedupe_by(items: list, key: str) -> list:
    """按 key 去重（忽略大小写、空格），保留第一次出现的那条。

    同时丢掉 key 为空白的条目——这类条目下游没法用。
    """
    seen = set()
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get(key, "") or "").strip()
        marker = name.lower().replace(" ", "")
        if not name or marker in seen:
            continue
        seen.add(marker)
        result.append({**item, key: name})
    return result


def check_non_empty(items: list, what: str, minimum: int = 1) -> list:
    """校验列表确实有内容，否则抛出可读的错误，避免脏数据流向下游。"""
    if len(items) < minimum:
        raise ValueError(f"{what} 只解析出 {len(items)} 条，少于要求的 {minimum} 条，模型输出可能异常")
    return items


def log(agent_name: str, message: str = "completed") -> None:
    """节点执行日志：用来确认 LangGraph 到底跑到了哪几个节点。"""
    print(f"[{agent_name}] {message}", flush=True)
