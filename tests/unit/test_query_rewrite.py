from rag_core.retrieval.rewrite import clean_rewrite_output


def test_rewrite_output_removes_answer_style_wrapping() -> None:
    assert (
        clean_rewrite_output("改写后的问题：MQTT 如何配置？\n答案是……", "它怎么配？")
        == "MQTT 如何配置？"
    )


def test_rewrite_output_falls_back_for_long_answer() -> None:
    original = "它怎么配？"
    assert clean_rewrite_output("这是一个很长的回答。" * 40, original) == original


def test_rewrite_output_falls_back_when_chinese_is_lost() -> None:
    original = "论文使用什么理论分析电网脆弱性？"
    corrupted = "?????????????????"

    assert clean_rewrite_output(corrupted, original) == original


def test_rewrite_output_falls_back_for_corrupted_mixed_language() -> None:
    original = "论文 Power grid vulnerability 使用什么理论？"
    corrupted = "?? Power grid vulnerability ?????????"

    assert clean_rewrite_output(corrupted, original) == original


def test_rewrite_output_keeps_valid_chinese_rewrite() -> None:
    assert clean_rewrite_output("Nginx 如何配置过滤规则？", "它的过滤规则怎么配？") == (
        "Nginx 如何配置过滤规则？"
    )


def test_rewrite_output_falls_back_when_chinese_intent_is_truncated() -> None:
    original = "论文使用什么理论分析北欧输电网的结构脆弱性？"
    truncated = "论文使用什么"

    assert clean_rewrite_output(truncated, original) == original
