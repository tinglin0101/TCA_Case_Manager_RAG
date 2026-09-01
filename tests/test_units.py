"""純函式單元測試：不需要向量庫、不需要模型，秒殺級，適合每次 commit 前都跑。

重點放在「答錯會出事」的地方：
  - 本地小模型的 JSON 輸出容錯解析（llm._parse_answer）——解析失敗時**必須**安全轉介，
    絕不可以變成「假裝答得出來」。這是整個 MVP 的醫療安全底線。
  - 切塊（store.chunk_text）不可以吃掉內容。
  - 轉介清單寫入／讀出。
"""
from __future__ import annotations

import pytest

from . import scoring

pytestmark = pytest.mark.unit


# --------------------------------------------------------------- LLM 輸出解析
def test_parse_clean_json():
    """標準 JSON：正常解析。"""
    llm = pytest.importorskip("app.llm")
    ans = llm._parse_answer('{"can_answer": true, "answer": "多喝水", "sources_used": [1, 2]}')
    assert ans.can_answer is True
    assert ans.answer == "多喝水"
    assert ans.sources_used == [1, 2]


def test_parse_json_wrapped_in_markdown_fence():
    """小模型常自作主張包上 ```json 圍欄。"""
    llm = pytest.importorskip("app.llm")
    raw = '```json\n{"can_answer": true, "answer": "採90度坐姿進食", "sources_used": [1]}\n```'
    ans = llm._parse_answer(raw)
    assert ans.can_answer is True
    assert ans.answer == "採90度坐姿進食"


def test_parse_json_with_surrounding_chatter():
    """前後多了廢話也要抓得到 JSON。"""
    llm = pytest.importorskip("app.llm")
    raw = '好的，以下是我的回答：\n{"can_answer": false, "answer": "我幫您轉給個管師", "sources_used": []}\n希望有幫上忙！'
    ans = llm._parse_answer(raw)
    assert ans.can_answer is False
    assert "個管師" in ans.answer


def test_parse_truncated_json_is_salvaged():
    """答案被截斷（少了收尾）時，救得回來就別浪費一個好答案。"""
    llm = pytest.importorskip("app.llm")
    raw = '{"can_answer": true, "answer": "傷口紅腫熱痛要立即就醫", "sources_used": [1'
    ans = llm._parse_answer(raw)
    assert ans.can_answer is True
    assert "立即就醫" in ans.answer


def test_parse_empty_output_escalates():
    """模型吐空字串 → 安全轉介，不可以假裝答得出來。"""
    llm = pytest.importorskip("app.llm")
    for raw in ("", "   ", None):
        ans = llm._parse_answer(raw)
        assert ans.can_answer is False, f"輸入 {raw!r} 竟然被判定為可回答"


def test_parse_garbage_escalates():
    """完全不是 JSON 的雜訊 → 安全轉介。"""
    llm = pytest.importorskip("app.llm")
    ans = llm._parse_answer("我不太確定耶，你要不要問問醫師？")
    assert ans.can_answer is False
    assert ans.answer, "轉介時仍要給病人一句話，不能是空白"


def test_parse_missing_answer_field_escalates():
    """有 can_answer 但沒有 answer 內容 → 安全轉介。"""
    llm = pytest.importorskip("app.llm")
    ans = llm._parse_answer('{"can_answer": true, "sources_used": [1]}')
    assert ans.can_answer is False


def test_answer_without_hits_escalates():
    """檢索不到任何段落時，直接轉介（不會呼叫模型）。"""
    llm = pytest.importorskip("app.llm")
    ans = llm.answer_question("我可以吃什麼？", [])
    assert ans.can_answer is False
    assert ans.sources_used == []


# --------------------------------------------------------------- 切塊
def test_chunk_short_text_stays_one_chunk():
    store = pytest.importorskip("app.store")
    chunks = store.chunk_text("傷口紅腫熱痛要立即就醫。", size=100, overlap=20)
    assert chunks == ["傷口紅腫熱痛要立即就醫。"]


def test_chunk_empty_text():
    store = pytest.importorskip("app.store")
    assert store.chunk_text("   \n\n  ") == []


def test_chunk_long_paragraph_splits_with_overlap():
    """過長段落會硬切；切點要有重疊，避免答案剛好被切成兩半而檢索不到。"""
    store = pytest.importorskip("app.store")
    text = "甲" * 250
    chunks = store.chunk_text(text, size=100, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    # 相鄰兩塊要有重疊 → 總字數會大於原文
    assert sum(len(c) for c in chunks) > len(text)


def test_chunk_keeps_all_content():
    """切塊不可以吃掉內容。"""
    store = pytest.importorskip("app.store")
    paragraphs = [f"第{i}段：吞嚥困難者應採90度坐姿，小量進食。" for i in range(6)]
    chunks = store.chunk_text("\n\n".join(paragraphs), size=60, overlap=10)
    joined = "".join(chunks)
    for p in paragraphs:
        assert p[:10] in joined, f"切塊後找不到「{p[:10]}」"


# --------------------------------------------------------------- 轉介清單
def test_escalation_roundtrip(tmp_path, monkeypatch):
    """寫入的轉介會讀得回來，且最新的排在最前面。"""
    escalations = pytest.importorskip("app.escalations")
    app_config = pytest.importorskip("app.config")
    monkeypatch.setattr(app_config, "ESCALATION_FILE", tmp_path / "escalations.jsonl")

    escalations.add_escalation("我的胰島素劑量該調成多少？")
    escalations.add_escalation("我今天血糖 210 正常嗎？")

    items = escalations.list_escalations()
    assert len(items) == 2
    assert items[0]["question"] == "我今天血糖 210 正常嗎？"
    assert items[0]["status"] == "pending"


def test_escalation_list_when_file_missing(tmp_path, monkeypatch):
    escalations = pytest.importorskip("app.escalations")
    app_config = pytest.importorskip("app.config")
    monkeypatch.setattr(app_config, "ESCALATION_FILE", tmp_path / "nope.jsonl")
    assert escalations.list_escalations() == []


# --------------------------------------------------------------- 文字擷取
def test_extract_utf8_text():
    extract = pytest.importorskip("app.extract")
    assert extract.extract_text("a.txt", "吞嚥困難".encode("utf-8")) == "吞嚥困難"


def test_extract_non_utf8_does_not_crash():
    """非 UTF-8 的檔案不能讓整條上傳流程炸掉。"""
    extract = pytest.importorskip("app.extract")
    assert isinstance(extract.extract_text("a.txt", "吞嚥困難".encode("big5")), str)


# --------------------------------------------------------------- 自動評分本身
def test_coverage_identical_is_one():
    ref = "採90度坐姿，並以小量食團進食，以減少嗆咳機會。"
    assert scoring.coverage(ref, ref) == pytest.approx(1.0)


def test_coverage_paraphrase_is_partial():
    """換句話說應該拿到部分分數，不是 0 也不是 1。"""
    ref = "採90度坐姿，並以小量食團進食，以減少嗆咳機會。"
    pred = "進食時請坐直到90度，每口份量少一點，可以減少嗆咳。"
    score = scoring.coverage(pred, ref)
    assert 0.1 < score < 1.0, f"覆蓋率 {score}"


def test_coverage_unrelated_is_low():
    ref = "採90度坐姿，並以小量食團進食，以減少嗆咳機會。"
    pred = "乳癌好發部位為乳房外上四分之一處。"
    assert scoring.coverage(pred, ref) < 0.1


def test_normalize_strips_punctuation_and_fullwidth():
    assert scoring.normalize("每天２０００ c.c.！") == "每天2000cc"


def test_same_document_matches_stem_and_filename():
    assert scoring.same_document("衛教單-防噎", "衛教單-防噎.pdf")
    assert scoring.same_document("衛教單-防噎.pdf", "衛教單-防噎.pdf")
    assert not scoring.same_document("衛教單-防跌倒", "衛教單-防噎.pdf")
    assert not scoring.same_document("", "衛教單-防噎.pdf")


def test_hit_expected_source():
    titles = ["衛教單-飲食糖尿病", "衛教單-防噎"]
    assert scoring.hit_expected_source(titles, "衛教單-防噎.pdf")
    assert not scoring.hit_expected_source(titles, "衛教單-認識乳癌.pdf")
