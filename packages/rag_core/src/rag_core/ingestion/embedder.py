from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

import httpx


class DeterministicHashEmbedder:
    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]", text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class OpenAICompatibleEmbedder:
    def __init__(
        self, base_url: str, api_key: str, model: str, dimension: int, timeout: float = 60.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": self.model, "input": list(texts), "dimensions": self.dimension}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings", json=payload, headers=headers
            )
            response.raise_for_status()
        vectors = [item["embedding"] for item in response.json()["data"]]
        if any(len(vector) != self.dimension for vector in vectors):
            raise ValueError(f"Embedding dimension mismatch, expected {self.dimension}")
        return vectors
