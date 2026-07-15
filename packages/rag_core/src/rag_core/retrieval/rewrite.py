from __future__ import annotations

from collections.abc import Sequence

import httpx


class HeuristicQueryRewriter:
    pronouns = ("它", "这个", "该项", "上述", "其", "那")

    async def rewrite(self, query: str, history: Sequence[dict[str, str]]) -> str:
        if not history or not any(pronoun in query for pronoun in self.pronouns):
            return query.strip()
        previous_user = next(
            (item["content"] for item in reversed(history) if item.get("role") == "user"), ""
        )
        topic = previous_user.strip().rstrip("？?")
        return f"基于上一轮关于“{topic}”的讨论，{query.strip()}" if topic else query.strip()


class OpenAICompatibleQueryRewriter:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def rewrite(self, query: str, history: Sequence[dict[str, str]]) -> str:
        prompt = "结合对话历史，将最后的问题改写为完整、自包含的检索问题。只输出改写结果。"
        messages = [
            {"role": "system", "content": prompt},
            *history[-8:],
            {"role": "user", "content": query},
        ]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "temperature": 0},
            )
            response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
