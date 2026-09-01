"""檢索層測試：問題有沒有撈到「題庫標註的那份衛教單」。

這一層不呼叫 LLM，所以快、而且結果穩定（同樣的向量庫每次跑都一樣），
最適合當回歸測試：改了切塊大小、換 embedding 模型、重新 ingest 之後跑一次就知道有沒有退步。

檢索撈錯文件的話，後面 LLM 再強也答不對；先把這層釘住。
"""
from __future__ import annotations

import pytest

from .dataset import EvalQuestion

pytestmark = pytest.mark.retrieval


def test_retrieval_returns_hits(q: EvalQuestion, result_for):
    """每題都要撈得到段落；撈不到通常代表向量庫是空的或 collection 名稱對不上。"""
    row = result_for(q)
    assert not row.retrieval_error, f"題號 {q.qid} 檢索時發生錯誤：{row.retrieval_error}"
    assert row.retrieved_titles, f"題號 {q.qid}「{q.question}」檢索不到任何段落"


def test_retrieval_hits_expected_source(q: EvalQuestion, result_for):
    """top-k 裡要出現題庫標註的來源文件。"""
    row = result_for(q)
    got = "、".join(dict.fromkeys(t for t in row.retrieved_titles if t)) or "（無）"
    assert row.retrieval_hit, (
        f"題號 {q.qid}「{q.question}」\n"
        f"  期望來源：{q.source}\n"
        f"  實際檢索到：{got}"
    )


@pytest.mark.gate
def test_gate_retrieval_recall(retrieval_rows, retrieval_metrics, gate, pytestconfig):
    """【驗收門檻】整體檢索命中率。"""
    missed = [r for r in retrieval_rows if not r.retrieval_hit]
    detail = "\n".join(
        f"  - 題號 {r.qid}「{r.question}」期望 {r.expected_source}，"
        f"實際 {'、'.join(dict.fromkeys(t for t in r.retrieved_titles if t)) or '（無）'}"
        for r in missed[:10]
    )
    if len(missed) > 10:
        detail += f"\n  …等共 {len(missed)} 題未命中"

    gate(
        "檢索命中率",
        retrieval_metrics["retrieval_recall"],
        ">=",
        pytestconfig.getoption("min_retrieval_recall"),
        detail=detail,
    )


@pytest.mark.gate
def test_gate_no_retrieval_errors(retrieval_rows, retrieval_metrics, gate):
    """【驗收門檻】檢索過程不可以有例外（例如向量庫損毀）。"""
    detail = "\n".join(
        f"  - 題號 {r.qid}：{r.retrieval_error}" for r in retrieval_rows if r.retrieval_error
    )
    gate("檢索執行錯誤題數", retrieval_metrics["retrieval_errors"], "<=", 0, kind="num", detail=detail)
