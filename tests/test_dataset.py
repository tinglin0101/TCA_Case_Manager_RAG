"""題庫健檢：先確定 data/eval/eval_questions.csv 本身是乾淨的。

題庫是人手維護的檔案，最容易出的錯是「少填答案」「來源文件打錯字」「題號重複」。
這些錯會讓後面的檢索／作答測試莫名其妙地失敗，所以先擋在這一層。
這一層不需要向量庫也不需要模型，任何機器上都跑得動（適合放進 CI）。
"""
from __future__ import annotations

import pytest

from .dataset import DOCS_DIR, EvalQuestion

pytestmark = pytest.mark.dataset


def test_question_bank_loads(questions):
    """題庫讀得到題目。"""
    assert questions, "題庫是空的，請確認 data/eval/eval_questions.csv 的「問題」欄有填。"


def test_question_bank_size(questions, pytestconfig):
    """題數符合 MVP 驗證規模（README：抽 30~50 題）。"""
    if pytestconfig.getoption("limit"):
        pytest.skip("用了 --limit 只跑部分題目，題數檢查沒有意義")
    assert len(questions) >= 30, (
        f"題庫只有 {len(questions)} 題；README 建議 30~50 題才有代表性。"
    )


def test_question_ids_are_unique(questions):
    """題號不可重複——結果報表與逐題比對都靠題號對應。"""
    seen: dict[str, EvalQuestion] = {}
    dup = []
    for q in questions:
        if q.qid in seen:
            dup.append(f"題號 {q.qid}：第 {seen[q.qid].row_no} 列與第 {q.row_no} 列")
        seen[q.qid] = q
    assert not dup, "題號重複：\n" + "\n".join(dup)


def test_questions_are_not_duplicated(questions):
    """同一題不要出現兩次，否則統計會被灌水。"""
    seen: dict[str, EvalQuestion] = {}
    dup = []
    for q in questions:
        key = q.question.strip()
        if key in seen:
            dup.append(f"第 {seen[key].row_no} 列與第 {q.row_no} 列：{key}")
        seen[key] = q
    assert not dup, "問題重複：\n" + "\n".join(dup)


def test_required_fields_filled(q: EvalQuestion):
    """每題都要有問題、參考答案、來源文件。"""
    missing = [
        name
        for name, value in (("問題", q.question), ("參考答案", q.reference), ("來源文件", q.source))
        if not value.strip()
    ]
    assert not missing, f"第 {q.row_no} 列（題號 {q.qid}）缺少：{'、'.join(missing)}"


def test_reference_answer_is_substantial(q: EvalQuestion):
    """參考答案不能只有一兩個字，否則覆蓋率分數沒有意義。"""
    assert len(q.reference.strip()) >= 8, (
        f"第 {q.row_no} 列（題號 {q.qid}）的參考答案太短：「{q.reference}」"
    )


def test_source_document_exists(q: EvalQuestion):
    """題庫標註的來源文件，必須真的在 data/docs/ 裡（不然永遠檢索不到）。"""
    if not q.source.strip():
        pytest.skip("這題沒有標註來源文件")
    candidates = {p.name for p in DOCS_DIR.iterdir()} if DOCS_DIR.exists() else set()
    assert q.source in candidates, (
        f"第 {q.row_no} 列（題號 {q.qid}）標註的來源文件「{q.source}」不在 {DOCS_DIR}。\n"
        f"目前有的檔案：{'、'.join(sorted(candidates)) or '（空）'}"
    )


def test_topic_is_filled(q: EvalQuestion):
    """衛教主題建議都填，結果報表才有分主題統計。"""
    assert q.topic.strip(), f"第 {q.row_no} 列（題號 {q.qid}）沒有填「衛教主題」"
