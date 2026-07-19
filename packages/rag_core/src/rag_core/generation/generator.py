from __future__ import annotations

import json
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

    def _request(
        self,
        query: str,
        contexts: Sequence[RetrievalResult],
        history: Sequence[dict[str, str]],
    ) -> dict:
        context_text = "\n\n".join(
            f"[文档{i + 1}: {item.filename}]\n{item.content}" for i, item in enumerate(contexts)
        )
        minimal_system_prompt = (
            "你是一位极简回复助手，回答必须极度精简。\n"
            "严格遵循：\n"
            "1. 只输出直接回答问题的核心内容，禁止任何客套话、背景、过程、建议、总结或引导语。\n"
            "2. 若问题不明确，最多用一句不带礼貌用语的追问。\n"
            "3. 答案本身不超过50字（代码或长列表除外）。若答案包含多个并列独立信息，可用换行分隔每项，以增强可读性，但每行仍不得添加额外解释。\n"
            "4. 排版精简：避免冗余空格、缩进、不必要的标点（如冒号、句号仅在确需时使用）。对于列表项，每项单独一行，不加序号或项目符号。对于代码，保持原始格式。\n"
            "5. 示例：天气回答应为“晴\n25~32℃\n东南风3级\nAQI良好”，而非段落。\n"
        )
        research_guidance_prompt = (
            "本土研究生‘实打实’科研推进指导：\n"
            "角色定义：你是一位熟悉中国理工科与社科量化方向的研究生科研顾问，理解本土研究生的真实科研生态，不以顶会式颠覆性创新或现实场景落地作为默认目标。\n"
            "核心认知：所有工作必须基于前人已有的开源代码、标准数据集或实验室传承的模拟模型；不考虑物理磨损、市场价格、实时政策等现实动态因素。\n"
            "创新点限定为在前人框架上进行排列组合，包括增加额外控制变量、引入新特征维度，或调整损失函数中的类别平衡、难易样本等权重，以提升离线评测指标。\n"
            "实验环境仅限服务器离线跑批，不涉及实地考察、硬件部署或大规模工程化验证。\n"
            "当用户问‘下一步怎么做’时，必须从以下五个实操维度中选择二至三个给出具体建议：\n"
            "基线对齐：确认当前代码能否完全复现原论文 Baseline；若不能，优先排查数据切分和随机种子。\n"
            "模块插入：指出现有模型中可无缝插入轻量级插件的位置，如 Encoder 后、Attention 前，并可选择 MLP 或小型 Transformer 层。\n"
            "变量增维：判断能否在数据预处理阶段将单一特征拆成多阶交叉特征，或拼接外部统计特征。\n"
            "权重博弈：针对样本不均衡或难例挖掘，给出 Loss 中 α 平衡因子或 γ 聚焦参数的具体调节区间。\n"
            "消融对照：固定随机种子，运行无插件、有插件、插件加权重调优三组实验并形成对比表格。\n"
            "禁止提及结合实际生产环境、考虑社会人文因素、开展实地调研验证或重新设计全套理论框架。\n"
            "科研指导按条目分点输出，每点不超过两行，直接给出操作细节，不含客套话。\n"
        )
        combined_system_prompt = minimal_system_prompt + research_guidance_prompt
        if contexts:
            system = combined_system_prompt + (
                "你是一个通用AI助手，同时可以使用企业知识库增强专业回答。"
                "参考文档与问题相关时，应优先依据文档回答，并在对应结论后使用[文档N]标注来源。"
                "参考文档不相关或不足时，可以使用通用知识正常回答，但不得编造文档内容或引用。"
                "不要因为参考文档没有答案就机械回复未找到。保留文档中的Markdown图片。"
            )
            user_content = f"问题：{query}\n\n可选参考文档：\n{context_text}"
        else:
            system = combined_system_prompt + (
                "你是一个友好、专业的通用AI助手。自然回答用户的问题。"
                "当前没有使用企业知识库材料，因此不要生成任何文档引用。"
            )
            user_content = query
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                *_normalized_history(history[-8:]),
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
        }

    async def generate(
        self,
        query: str,
        contexts: Sequence[RetrievalResult],
        history: Sequence[dict[str, str]] = (),
    ) -> GeneratedAnswer:
        payload = self._request(query, contexts, history)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            if response.is_error:
                raise RuntimeError(
                    f"Model gateway returned {response.status_code}: {response.text[:2000]}"
                )
        answer = response.json()["choices"][0]["message"]["content"]
        citations = _cited_contexts(answer, contexts)
        return GeneratedAnswer(answer=answer, rewritten_query=query, citations=citations)

    async def stream(
        self,
        query: str,
        contexts: Sequence[RetrievalResult],
        history: Sequence[dict[str, str]] = (),
    ) -> AsyncIterator[str]:
        payload = self._request(query, contexts, history) | {"stream": True}
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
                        f"Model gateway returned {response.status_code}: {body[:2000]}"
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
                        yield delta

def replace_asset_urls(markdown: str, mapping: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        label, path = match.group(1), match.group(2)
        return f"![{label}]({mapping.get(path, path)})"

    return re.sub(r"!\[([^]]*)]\(([^)]+)\)", replace, markdown)


def citations_from_answer(
    answer: str, contexts: Sequence[RetrievalResult]
) -> list[Citation]:
    return _cited_contexts(answer, contexts)

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