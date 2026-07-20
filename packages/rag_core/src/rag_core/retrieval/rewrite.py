from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

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

    async def stream(self, query: str, history: Sequence[dict[str, str]]) -> AsyncIterator[str]:
        yield await self.rewrite(query, history)


class OpenAICompatibleQueryRewriter:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _request(self, query: str, history: Sequence[dict[str, str]]) -> dict[str, object]:
        prompt = (
            "你是检索词改写器，不是问答助手。\n"
            "你的唯一任务是把用户最后一句话改写成一个完整、自包含的检索问题。\n"
            "只能输出改写后的一个问题，不能回答问题，不能解释原因，不能输出步骤、结论、摘要、引用或客套话。\n"
            "如果原问题已经完整，原样输出；如果是寒暄或不需要改写，原样输出。\n"
            "保留用户原本的疑问意图，不要替用户补充答案。"
        )
        context = [
            {"role": "user", "content": item.get("content", "")}
            for item in history[-12:]
            if item.get("role") == "user" and item.get("content")
        ]
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                *context,
                {
                    "role": "user",
                    "content": f"只改写下面的问题，不要回答：\n{query}",
                },
            ],
            "temperature": 0,
            "max_tokens": 128,
        }

    async def rewrite(self, query: str, history: Sequence[dict[str, str]]) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=self._request(query, history),
            )
            response.raise_for_status()
        return clean_rewrite_output(response.json()["choices"][0]["message"]["content"], query)

    async def stream(self, query: str, history: Sequence[dict[str, str]]) -> AsyncIterator[str]:
        payload = self._request(query, history) | {"stream": True}
        parts: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as response:
                if response.is_error:
                    body = (await response.aread()).decode(errors="replace")
                    raise RuntimeError(
                        f"Rewrite gateway returned {response.status_code}: {body[:2000]}"
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    delta = event.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        parts.append(delta)
        cleaned = clean_rewrite_output("".join(parts), query)
        yield cleaned


def clean_rewrite_output(raw: str, original_query: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return original_query.strip()
    if "</think>" in cleaned:
        cleaned = cleaned.rsplit("</think>", 1)[-1].strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.strip("`").strip()
    for prefix in ("改写结果：", "改写后的问题：", "检索问题：", "Query:", "Rewritten query:"):
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix) :].strip()
            break
    if "\n" in cleaned:
        cleaned = cleaned.splitlines()[0].strip()
    if len(cleaned) > max(300, len(original_query.strip()) * 8):
        return original_query.strip()
    if _is_suspicious_rewrite(cleaned, original_query):
        return original_query.strip()
    return cleaned or original_query.strip()


def _is_suspicious_rewrite(cleaned: str, original_query: str) -> bool:
    if "�" in cleaned:
        return True
    original_cjk_count = sum("\u4e00" <= character <= "\u9fff" for character in original_query)
    if not original_cjk_count:
        return False
    cleaned_cjk_count = sum("\u4e00" <= character <= "\u9fff" for character in cleaned)
    if cleaned_cjk_count == 0:
        return True
    minimum_retained_cjk = max(2, (original_cjk_count + 1) // 2)
    if cleaned_cjk_count < minimum_retained_cjk:
        return True
    placeholder_count = cleaned.count("?") + cleaned.count("？")
    return placeholder_count >= 3 and placeholder_count > cleaned_cjk_count
