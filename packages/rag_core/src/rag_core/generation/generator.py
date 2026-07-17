from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

import httpx

from rag_core.models import Citation, GeneratedAnswer, RetrievalResult


class ExtractiveAnswerGenerator:
    async def generate(
        self,
        query: str,
        contexts: Sequence[RetrievalResult],
        history: Sequence[dict[str, str]] = (),
    ) -> GeneratedAnswer:
        del history
        if not contexts:
            return GeneratedAnswer(
                answer="你好！有什么可以帮你？",
                rewritten_query=query,
                citations=[],
            )
        sections = []
        for context in contexts[:3]:
            excerpt = _best_excerpt(query, context.content)
            sections.append(f"### {context.filename}\n{excerpt}")
        citations = [
            Citation(
                context.document_id,
                context.filename,
                context.score,
                context.metadata.get("source_url"),
            )
            for context in contexts
        ]
        return GeneratedAnswer(
            answer="\n\n".join(sections), rewritten_query=query, citations=citations
        )

    async def stream(
        self,
        query: str,
        contexts: Sequence[RetrievalResult],
        history: Sequence[dict[str, str]] = (),
    ) -> AsyncIterator[str]:
        answer = await self.generate(query, contexts, history)
        for line in answer.answer.splitlines(keepends=True):
            yield line


class OpenAICompatibleAnswerGenerator:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def generate(
        self,
        query: str,
        contexts: Sequence[RetrievalResult],
        history: Sequence[dict[str, str]] = (),
    ) -> GeneratedAnswer:
        context_text = "\n\n".join(
            f"[文档{i + 1}: {item.filename}]\n{item.content}" for i, item in enumerate(contexts)
        )
        if contexts:
            system = (
                "你是一个通用AI助手，同时可以使用企业知识库增强专业回答。"
                "参考文档与问题相关时，应优先依据文档回答，并在对应结论后使用[文档N]标注来源。"
                "参考文档不相关或不足时，可以使用通用知识正常回答，但不得编造文档内容或引用。"
                "不要因为参考文档没有答案就机械回复未找到。保留文档中的Markdown图片。"
            )
            user_content = f"问题：{query}\n\n可选参考文档：\n{context_text}"
        else:
            system = (
                "你是一个友好、专业的通用AI助手。自然回答用户的问题。"
                "当前没有使用企业知识库材料，因此不要生成任何文档引用。"
            )
            user_content = query
        messages = [
            {"role": "system", "content": system},
            *_normalized_history(history[-8:]),
            {"role": "user", "content": user_content},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        citations = _cited_contexts(answer, contexts)
        return GeneratedAnswer(answer=answer, rewritten_query=query, citations=citations)

    async def stream(
        self,
        query: str,
        contexts: Sequence[RetrievalResult],
        history: Sequence[dict[str, str]] = (),
    ) -> AsyncIterator[str]:
        answer = await self.generate(query, contexts, history)
        yield answer.answer


def replace_asset_urls(markdown: str, mapping: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        label, path = match.group(1), match.group(2)
        return f"![{label}]({mapping.get(path, path)})"

    return re.sub(r"!\[([^]]*)]\(([^)]+)\)", replace, markdown)


def _cited_contexts(
    answer: str, contexts: Sequence[RetrievalResult]
) -> list[Citation]:
    cited_indexes = {
        int(value) - 1 for value in re.findall(r"\[文档(\d+)]", answer) if int(value) > 0
    }
    return [
        Citation(item.document_id, item.filename, item.score, item.metadata.get("source_url"))
        for index, item in enumerate(contexts)
        if index in cited_indexes
    ]


def _normalized_history(history: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"role": item["role"], "content": item["content"]}
        for item in history
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]


def _best_excerpt(query: str, content: str, limit: int = 900) -> str:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]{2,6}", query)]
    paragraphs = [item.strip() for item in content.split("\n\n") if item.strip()]
    ranked = sorted(
        paragraphs, key=lambda item: sum(term in item.lower() for term in terms), reverse=True
    )
    selected = "\n\n".join(ranked[:3]) if ranked else content
    return selected[:limit]