from rag_core.services import _should_use_retrieval


def test_model_metadata_questions_bypass_retrieval() -> None:
    direct_questions = (
        "你的模型是什么？",
        "你用的什么模型",
        "你的知识截止时间是什么时候？",
        "你的知识库时间到哪？",
        "What model are you?",
        "What is your knowledge cutoff?",
    )

    assert all(not _should_use_retrieval(question) for question in direct_questions)


def test_professional_questions_still_use_retrieval() -> None:
    assert _should_use_retrieval("MQTT 的连接参数应该如何配置？")