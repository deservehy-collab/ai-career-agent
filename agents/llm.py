"""共享的 LLM 配置与结构化输出工具。

整个项目只在这里创建一个 Ollama 模型实例，其他 Agent 直接 import 使用。
"""

import json
import re
from typing import Type, TypeVar

from langchain_ollama import ChatOllama
from pydantic import BaseModel

MODEL_NAME = "qwen2.5:3b"

# 全局唯一实例，避免每个 Agent 重复创建连接
llm = ChatOllama(model=MODEL_NAME, temperature=0.2)

T = TypeVar("T", bound=BaseModel)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_CODE_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def _extract_json(text: str) -> dict:
    """从模型输出里挖出第一个 JSON 对象（容忍 ```json 包裹和前后废话）。"""
    cleaned = _CODE_FENCE.sub("", text.strip())
    match = _JSON_OBJECT.search(cleaned)
    if not match:
        raise ValueError(f"输出里找不到 JSON 对象：{text[:200]}")
    return json.loads(match.group(0))


def structured_invoke(prompt: str, schema: Type[T]) -> T:
    """让模型按 schema 输出结构化结果，返回校验过的 Pydantic 对象。

    小模型的 json_schema 支持偶尔不稳定，所以准备了两条路：
    1. Ollama 原生 json_schema 结构化输出（首选）
    2. format="json" + 手动解析（降级）
    两条都失败时抛 RuntimeError，并把两次的原始错误带上，方便定位。
    """
    try:
        result = llm.with_structured_output(schema, method="json_schema").invoke(prompt)
        # 正常情况下已经是 schema 实例，个别版本会返回 dict
        return result if isinstance(result, schema) else schema.model_validate(result)
    except Exception as structured_error:
        try:
            raw = llm.invoke(prompt, format="json").content
            return schema.model_validate(_extract_json(raw))
        except Exception as parse_error:
            raise RuntimeError(
                f"[{schema.__name__}] 结构化输出失败\n"
                f"  json_schema 尝试：{type(structured_error).__name__}: {structured_error}\n"
                f"  JSON 解析尝试：{type(parse_error).__name__}: {parse_error}"
            ) from parse_error
