from __future__ import annotations

import json
import re
from collections import Counter

import httpx

from rag_core.models import Document, SemanticMetadata


class HeuristicMetadataEnricher:
    stopwords = {
        "我们",
        "可以",
        "进行",
        "使用",
        "以及",
        "这个",
        "一个",
        "如果",
        "需要",
        "通过",
        "相关",
        "文档",
        "系统",
    }

    async def enrich(self, document: Document) -> SemanticMetadata:
        plain = re.sub(r"[#>*`|\[\]()!_]", " ", document.content)
        sentences = [
            item.strip() for item in re.split(r"[。！？\n]+", plain) if len(item.strip()) >= 8
        ]
        summary = (sentences[0] if sentences else plain.strip())[:180]
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{2,}|[\u4e00-\u9fff]{2,8}", plain)
        counts = Counter(token for token in tokens if token not in self.stopwords)
        keywords = [token for token, _ in counts.most_common(8)]
        subject = document.title or document.filename
        questions = [f"{subject}主要介绍什么？"]
        questions.extend(f"{subject}中的{keyword}如何配置或使用？" for keyword in keywords[:4])
        return SemanticMetadata(
            summary=summary,
            keywords=keywords[:8],
            questions=questions[:5],
            prompt_version="heuristic-v1",
            model="heuristic",
        )


class OpenAICompatibleMetadataEnricher:
    prompt_version = "metadata-v1"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def enrich(self, document: Document) -> SemanticMetadata:
        prompt = (
            "阅读技术文档并只返回JSON：summary为一句话摘要；keywords为5到8个技术术语；"
            "questions为3到5个该文档能回答的问题。\n\n标题："
            f"{document.title}\n内容：{document.content[:24000]}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return SemanticMetadata(
            summary=str(data.get("summary", ""))[:500],
            keywords=[str(item) for item in data.get("keywords", [])][:8],
            questions=[str(item) for item in data.get("questions", [])][:5],
            prompt_version=self.prompt_version,
            model=self.model,
        )
