"""端到端作答測試（需要 --e2e，會真的呼叫 LLM）。

題庫這 50 題都是「衛教單裡查得到答案」的題目，所以合格的行為是：
    答得出來、附得出出處、而且引用的就是題庫標註的那份衛教單。

被轉介＝誤轉介（false escalation），會把個管師的待辦清單洗版；
這正是 note.md 記錄、待團隊拍板的那個問題，這裡把它變成可量化、可回歸的數字。

注意：覆蓋率只是「有沒有講到重點」的粗篩，**不是醫療正確性**。
最終準確率仍請個案管理師用 scripts/run_eval.py 的 Excel 人工打分。
"""
from __future__ import annotations

import pytest

from .dataset import EvalQuestion

pytestmark = [pytest.mark.e2e]


def _require_clean_run(q: EvalQuestion, row):
    """跳過「不是這個測試該負責」的題，讓一個根因只炸出一個失敗。

    - 題庫標註應轉介的題 → 由 test_escalation.py 負責
    - 作答時就出錯的題 → 由 test_no_execution_error 負責，不必再重複報一次
    """
    if q.expect_escalation:
        pytest.skip("這題題庫標註為「應轉介」，由 test_escalation.py 負責")
    if row.answer_error:
        pytest.skip("這題作答時發生錯誤（已由 test_no_execution_error 報告）")


def test_no_execution_error(q: EvalQuestion, answer_for):
    """作答過程不可以拋例外（連不上模型、JSON 壞掉等）。"""
    row = answer_for(q)
    assert not row.answer_error, f"題號 {q.qid}「{q.question}」作答時發生錯誤：{row.answer_error}"


def test_not_falsely_escalated(q: EvalQuestion, answer_for):
    """衛教單答得出來的題目，不該被轉介。"""
    row = answer_for(q)
    _require_clean_run(q, row)
    assert not row.escalated, (
        f"題號 {q.qid}「{q.question}」被轉介，但這題衛教單（{q.source}）有答案。\n"
        f"  模型回答：{row.answer[:120]}"
    )


def test_answer_is_not_empty(q: EvalQuestion, answer_for):
    """不論答不答得出來，都要給病人一段話，不能是空白。"""
    row = answer_for(q)
    if row.answer_error:
        pytest.skip("這題作答時發生錯誤（已由 test_no_execution_error 報告）")
    assert row.answer.strip(), f"題號 {q.qid}「{q.question}」回答是空白"


def test_answer_has_citation(q: EvalQuestion, answer_for):
    """回答要附出處——「有根據、附出處」是這個 MVP 的核心賣點。"""
    row = answer_for(q)
    _require_clean_run(q, row)
    if row.escalated:
        pytest.skip("這題被轉介（另由 test_not_falsely_escalated 記錄）")
    assert row.has_citation, f"題號 {q.qid}「{q.question}」有回答卻沒附任何出處"


def test_answer_covers_reference(q: EvalQuestion, answer_for, pytestconfig):
    """回答要跟標準答案有基本重疊，用來抓「答非所問」。"""
    row = answer_for(q)
    _require_clean_run(q, row)
    if row.escalated:
        pytest.skip("這題被轉介，沒有內容可比對")
    floor = pytestconfig.getoption("min_item_coverage")
    assert row.coverage >= floor, (
        f"題號 {q.qid}「{q.question}」覆蓋率只有 {row.coverage:.0%}（門檻 {floor:.0%}），疑似答非所問。\n"
        f"  參考答案：{q.reference}\n"
        f"  模型回答：{row.answer}"
    )


# ------------------------------------------------------------------ 驗收門檻
@pytest.mark.gate
def test_gate_false_escalation_rate(answer_rows, answer_metrics, gate, pytestconfig):
    """【驗收門檻】誤轉介率：答得出來卻轉給個管師的比例。"""
    bad = [r for r in answer_rows if r.escalated and not r.expect_escalation]
    detail = "\n".join(f"  - 題號 {r.qid}「{r.question}」" for r in bad[:10])
    if len(bad) > 10:
        detail += f"\n  …等共 {len(bad)} 題誤轉介"
    gate(
        "誤轉介率",
        answer_metrics["false_escalation_rate"],
        "<=",
        pytestconfig.getoption("max_escalation_rate"),
        detail=detail,
    )


@pytest.mark.gate
def test_gate_citation_rate(answer_rows, answer_metrics, gate, pytestconfig):
    """【驗收門檻】有附出處的比例（在有回答的題目中）。"""
    bad = [r for r in answer_rows if r.answered and not r.has_citation]
    detail = "\n".join(f"  - 題號 {r.qid}「{r.question}」" for r in bad[:10])
    gate(
        "回答附出處比例",
        answer_metrics["citation_rate"],
        ">=",
        pytestconfig.getoption("min_citation_rate"),
        detail=detail,
    )


@pytest.mark.gate
def test_gate_citation_accuracy(answer_rows, answer_metrics, gate, pytestconfig):
    """【驗收門檻】引用文件正確率：引到的就是題庫標註的那份衛教單。"""
    bad = [r for r in answer_rows if r.answered and not r.citation_hit]
    detail = "\n".join(
        f"  - 題號 {r.qid}「{r.question}」期望 {r.expected_source}，"
        f"引用 {'、'.join(r.cited_titles) or '（無）'}"
        for r in bad[:10]
    )
    gate(
        "引用文件正確率",
        answer_metrics["citation_accuracy"],
        ">=",
        pytestconfig.getoption("min_citation_accuracy"),
        detail=detail,
    )


@pytest.mark.gate
def test_gate_average_coverage(answer_rows, answer_metrics, gate, pytestconfig):
    """【驗收門檻】平均參考答案覆蓋率（粗篩答非所問，非醫療正確性）。"""
    worst = sorted(
        (r for r in answer_rows if r.answered and r.coverage is not None),
        key=lambda r: r.coverage,
    )[:5]
    detail = "\n".join(f"  - 題號 {r.qid} 覆蓋率 {r.coverage:.0%}「{r.question}」" for r in worst)
    gate(
        "平均參考答案覆蓋率",
        answer_metrics["avg_coverage"],
        ">=",
        pytestconfig.getoption("min_coverage"),
        detail="覆蓋率最低的幾題：\n" + detail if detail else "",
    )


@pytest.mark.gate
def test_gate_no_answer_errors(answer_rows, answer_metrics, gate):
    """【驗收門檻】整批跑完不可以有執行錯誤。"""
    detail = "\n".join(
        f"  - 題號 {r.qid}：{r.answer_error}" for r in answer_rows if r.answer_error
    )
    gate("作答執行錯誤題數", answer_metrics["answer_errors"], "<=", 0, kind="num", detail=detail)
