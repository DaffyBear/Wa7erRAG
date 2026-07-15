from __future__ import annotations

import re

import httpx


class HeuristicHydeGenerator:
    async def generate(self, query: str) -> str:
        normalized = query.strip().rstrip("？?")
        terms = re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]{2,8}", normalized)
        topic = "、".join(terms[:6]) or normalized
        return (
            f"技术文档中关于{topic}的说明通常包含适用场景、前置条件、配置步骤、"
            "参数含义、示例、验证方法以及常见故障排查。"
        )


class OpenAICompatibleHydeGenerator:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def generate(self, query: str) -> str:
        prompt = (
            "请为下面的企业技术问题生成一段可能出现在正确技术文档中的假设答案。"
            "答案用于向量检索，不要解释过程，不要声称信息已验证；应包含可能的技术术语、"
            "配置项、步骤和同义表达，控制在300字以内。\n\n问题："
            f"{query}"
        )
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
