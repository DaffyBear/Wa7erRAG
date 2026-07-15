from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

import httpx

from rag_core.models import Citation, GeneratedAnswer, RetrievalResult


class ExtractiveAnswerGenerator:
    async def generate(self, query: str, contexts: Sequence[RetrievalResult]) -> GeneratedAnswer:
        if not contexts:
            return GeneratedAnswer(answer="未找到相关信息。", rewritten_query=query, citations=[])
        excerpts: list[str] = []
        for context in contexts[:3]:
            excerpt = _best_excerpt(query, context.content)
            excerpts.append(f"### {context.filename}\n{excerpt}")
        citations = [
            Citation(
                document_id=context.document_id,
                filename=context.filename,
                score=round(context.score, 6),
                source_url=context.metadata.get("source_url"),
            )
            for context in contexts
        ]
        return GeneratedAnswer(
            answer="\n\n".join(excerpts), rewritten_query=query, citations=citations
        )

    async def stream(self, query: str, contexts: Sequence[RetrievalResult]) -> AsyncIterator[str]:
        answer = await self.generate(query, contexts)
        for line in answer.answer.splitlines(keepends=True):
            yield line


class OpenAICompatibleAnswerGenerator:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def generate(self, query: str, contexts: Sequence[RetrievalResult]) -> GeneratedAnswer:
        context_text = "\n\n".join(
            f"[文档{i + 1}: {item.filename}]\n{item.content}" for i, item in enumerate(contexts)
        )
        system = (
            "你是企业内部技术知识助手。只能根据给定文档回答；找不到时明确说未找到相关信息。"
            "保留文档中的Markdown图片；关键结论使用[文档N]标注来源，不得编造引用。"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"问题：{query}\n\n参考文档：\n{context_text}"},
            ],
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
        citations = [
            Citation(item.document_id, item.filename, item.score, item.metadata.get("source_url"))
            for item in contexts
        ]
        return GeneratedAnswer(answer=answer, rewritten_query=query, citations=citations)

    async def stream(self, query: str, contexts: Sequence[RetrievalResult]) -> AsyncIterator[str]:
        answer = await self.generate(query, contexts)
        yield answer.answer


def replace_asset_urls(markdown: str, mapping: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        label, path = match.group(1), match.group(2)
        return f"![{label}]({mapping.get(path, path)})"

    return re.sub(r"!\[([^]]*)]\(([^)]+)\)", replace, markdown)


def _best_excerpt(query: str, content: str, limit: int = 900) -> str:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]{2,6}", query)]
    paragraphs = [item.strip() for item in content.split("\n\n") if item.strip()]
    ranked = sorted(
        paragraphs, key=lambda item: sum(term in item.lower() for term in terms), reverse=True
    )
    selected = "\n\n".join(ranked[:3]) if ranked else content
    return selected[:limit]
