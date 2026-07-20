from __future__ import annotations

import json
import re
from collections.abc import Sequence

import httpx

from rag_core.models import RetrievalDecision

_DIRECT_EXACT = {
    "你好",
    "您好",
    "嗨",
    "hi",
    "hello",
    "在吗",
    "谢谢",
    "感谢",
    "再见",
    "拜拜",
    "你是谁",
    "你能做什么",
    "介绍一下你自己",
}

_DIRECT_MARKERS = (
    "你是什么模型",
    "你用的什么模型",
    "你的模型是什么",
    "你的模型版本",
    "当前模型是什么",
    "模型名称是什么",
    "知识截止时间",
    "知识更新到什么时候",
    "知识库时间到哪",
    "知识库更新到什么时候",
    "训练数据截止",
    "knowledgecutoff",
    "whatmodelareyou",
    "whichmodelareyou",
)

_DIRECT_TASK_PREFIXES = (
    "翻译",
    "润色",
    "改写这段",
    "改写以下",
    "总结这段",
    "总结以下",
)

_RETRIEVAL_MARKERS = (
    "根据知识库",
    "查询知识库",
    "从知识库",
    "根据文档",
    "文档中",
    "这份文档",
    "这篇论文",
    "该论文",
    "引用来源",
    "原文出处",
    "参考文献",
)

_FILE_OR_IDENTIFIER = re.compile(
    r"(?:\.(?:pdf|docx?|md|txt|html?)\b)|(?:[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+)",
    re.IGNORECASE,
)


class RuleBasedRetrievalRouter:
    async def decide(self, query: str, history: Sequence[dict[str, str]] = ()) -> RetrievalDecision:
        decision = deterministic_retrieval_decision(query)
        return RetrievalDecision(
            needs_retrieval=True if decision is None else decision,
            source="rule" if decision is not None else "rule_default",
        )


class OpenAICompatibleRetrievalRouter:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def decide(self, query: str, history: Sequence[dict[str, str]] = ()) -> RetrievalDecision:
        rule_decision = deterministic_retrieval_decision(query)
        if rule_decision is not None:
            return RetrievalDecision(rule_decision, "rule")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是RAG检索路由器，不是问答助手。"
                        "判断回答用户最后一个问题是否需要查询企业知识库或论文资料库。"
                        "涉及特定文档、论文、配置、错误码、内部事实、引用来源或需要外部证据时为true。"
                        "寒暄、创作、翻译、润色、用户已提供文本的解释，以及无需外部证据的通用问题为false。"
                        "不允许回答问题，不允许解释，只能输出严格JSON："
                        '{"needs_retrieval":true}或{"needs_retrieval":false}'
                    ),
                },
                {
                    "role": "user",
                    "content": _router_user_content(query, history),
                },
            ],
            "temperature": 0,
            "max_tokens": 256,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        return RetrievalDecision(parse_retrieval_decision(raw), "model")


def deterministic_retrieval_decision(query: str) -> bool | None:
    normalized = "".join(query.strip().lower().split())
    if not normalized:
        return False
    if normalized in _DIRECT_EXACT:
        return False
    if any(marker in normalized for marker in _DIRECT_MARKERS):
        return False
    if any(normalized.startswith(prefix) for prefix in _DIRECT_TASK_PREFIXES):
        return False
    if any(marker in normalized for marker in _RETRIEVAL_MARKERS):
        return True
    if _FILE_OR_IDENTIFIER.search(query):
        return True
    return None


def parse_retrieval_decision(raw: str) -> bool:
    cleaned = raw.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        payload = json.loads(cleaned)
    except (TypeError, ValueError) as error:
        raise ValueError("Retrieval router returned invalid JSON") from error
    if set(payload) != {"needs_retrieval"} or not isinstance(payload["needs_retrieval"], bool):
        raise ValueError("Retrieval router JSON must contain one boolean field")
    return payload["needs_retrieval"]


def _router_user_content(query: str, history: Sequence[dict[str, str]]) -> str:
    context = [
        f"{item.get('role', '')}: {item.get('content', '')}"
        for item in history[-6:]
        if item.get("content")
    ]
    history_text = "\n".join(context) if context else "无"
    return f"最近对话：\n{history_text}\n\n最后一个问题：\n{query}"
