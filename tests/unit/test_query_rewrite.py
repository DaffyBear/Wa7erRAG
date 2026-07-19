from rag_core.retrieval.rewrite import clean_rewrite_output


def test_rewrite_output_removes_answer_style_wrapping() -> None:
    assert clean_rewrite_output("改写后的问题：MQTT 如何配置？\n答案是……", "它怎么配？") == "MQTT 如何配置？"


def test_rewrite_output_falls_back_for_long_answer() -> None:
    original = "它怎么配？"
    assert clean_rewrite_output("这是一个很长的回答。" * 40, original) == original