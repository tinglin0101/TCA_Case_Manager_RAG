"""跑管線：逐題做「檢索 → LLM 作答」，把結果收成可評分、可存檔的 RunRow。

刻意走和 /ask 端點相同的路徑（store.query → llm.answer_question），
所以測到的就是產品的真實行為；但**不呼叫 escalations.add_escalation**，
測試不會污染正式的轉介清單（data/escalations.jsonl）。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import scoring
from .dataset import EvalQuestion


@dataclass
class RunRow:
    """一題的執行結果 + 自動評分。answered 為 None 代表這輪沒跑 LLM（只跑檢索）。"""

    qid: str
    topic: str
    question: str
    reference: str
    expected_source: str
    # 題庫標註「這題該不該轉介」；None＝題庫沒這欄，預設視為「答得出來的衛教題」。
    expect_escalation: bool | None = None

    # --- 檢索層 ---
    retrieved_titles: list[str] = field(default_factory=list)
    # 檢索到的段落原文：作答階段直接沿用（不必再查一次向量庫），
    # 也讓結果 JSON 自帶「模型當時看到的內容」，事後查為什麼答成這樣很有用。
    retrieved_texts: list[str] = field(default_factory=list)
    distances: list[float] = field(default_factory=list)
    retrieval_hit: bool = False        # top-k 裡有沒有題庫標註的來源文件
    retrieval_rank: int | None = None  # 命中的名次（1 起算），沒命中為 None

    # --- LLM 層（沒開 --e2e 時全為 None／空） ---
    answered: bool | None = None       # 模型判定可回答
    answer: str = ""
    cited_titles: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)  # 給報表看的引用片段
    citation_hit: bool = False         # 引用到的文件是不是題庫標註的那份
    coverage: float | None = None      # 對參考答案的覆蓋率
    f1: float | None = None
    elapsed: float = 0.0

    # 兩層的錯誤分開記：作答失敗不該讓檢索層的測試跟著紅。
    retrieval_error: str = ""
    answer_error: str = ""

    @property
    def error(self) -> str:
        return self.answer_error or self.retrieval_error

    @property
    def escalated(self) -> bool:
        """模型判定不能回答 → 會被轉介個管師。執行錯誤也算轉介（llm 層的安全預設）。"""
        return self.answered is False

    @property
    def has_citation(self) -> bool:
        return bool(self.cited_titles)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunRow":
        known = {f for f in cls.__dataclass_fields__}  # 忽略舊版 JSON 的多餘欄位
        return cls(**{k: v for k, v in d.items() if k in known})


def _new_row(q: EvalQuestion) -> RunRow:
    return RunRow(
        qid=q.qid,
        topic=q.topic,
        question=q.question,
        reference=q.reference,
        expected_source=q.source,
        expect_escalation=q.expect_escalation,
    )


def run_retrieval(questions, log=print) -> list[RunRow]:
    """逐題檢索。只碰向量庫，不呼叫 LLM，速度快（適合當回歸測試的第一道關卡）。"""
    from app import store  # 延後 import：讓沒裝 chromadb 的環境也能跑題庫健檢

    rows: list[RunRow] = []
    total = len(questions)
    for i, q in enumerate(questions, start=1):
        row = _new_row(q)
        t0 = time.perf_counter()
        try:
            hits = store.query(q.question)
            row.retrieved_titles = [h.get("title") or "" for h in hits]
            row.retrieved_texts = [h.get("text") or "" for h in hits]
            row.distances = [round(float(h.get("distance") or 0), 4) for h in hits]
            for rank, title in enumerate(row.retrieved_titles, start=1):
                if scoring.same_document(title, q.source):
                    row.retrieval_hit = True
                    row.retrieval_rank = rank
                    break
        except Exception as e:  # noqa: BLE001 — 單題失敗不中斷整批
            row.retrieval_error = f"{type(e).__name__}: {e}"
        row.elapsed = time.perf_counter() - t0
        rows.append(row)
        log(f"[檢索 {i}/{total}] {'命中' if row.retrieval_hit else '未命中'}  {q.question[:24]}")
    return rows


def run_answers(rows: list[RunRow], log=print) -> list[RunRow]:
    """在檢索結果之上逐題呼叫 LLM 作答，並自動評分（就地更新 rows）。

    直接沿用 run_retrieval 存下來的段落，不再查一次向量庫：
    這樣 sources_used 的編號必定對得上報表顯示的檢索結果，也少跑一半的檢索。
    """
    from app import llm

    total = len(rows)
    for i, row in enumerate(rows, start=1):
        t0 = time.perf_counter()
        try:
            hits = [
                {"title": t, "text": x}
                for t, x in zip(row.retrieved_titles, row.retrieved_texts)
            ]
            ans = llm.answer_question(row.question, hits)
            row.answered = bool(ans.can_answer)
            row.answer = ans.answer or ""
            for idx in ans.sources_used:
                if 1 <= idx <= len(hits):
                    h = hits[idx - 1]
                    row.cited_titles.append(h.get("title") or "")
                    row.citations.append(f"[{idx}] {h.get('title')}：{(h.get('text') or '')[:120]}")
            row.citation_hit = scoring.hit_expected_source(row.cited_titles, row.expected_source)
            row.coverage = round(scoring.coverage(row.answer, row.reference), 4)
            row.f1 = round(scoring.f1(row.answer, row.reference), 4)
        except Exception as e:  # noqa: BLE001
            row.answer_error = f"{type(e).__name__}: {e}"
            row.answered = False  # 與 llm.py 一致：出錯就當作要轉介，絕不假裝答得出來
            row.coverage = 0.0
            row.f1 = 0.0
        row.elapsed += time.perf_counter() - t0
        flag = "⚠ 錯誤" if row.error else ("→ 轉介" if row.escalated else f"已回答 覆蓋率{row.coverage:.0%}")
        log(f"[作答 {i}/{total}] {flag}  {row.question[:24]}")
    return rows


def save_rows(rows: list[RunRow], path: Path) -> Path:
    """把整批結果存成 JSON，之後可用 --from-json 重跑評分而不必再呼叫模型。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_rows(path: Path) -> list[RunRow]:
    """讀回先前的結果並「重新評分」。

    重算而不是直接沿用檔案裡的分數，這樣改了 scoring.py 的算法後，
    舊的結果檔也能用新算法重跑一次比較，不必再花時間呼叫模型。
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    data = raw.get("rows", raw) if isinstance(raw, dict) else raw  # 相容報表 JSON 與純陣列
    return rescore([RunRow.from_dict(d) for d in data])


def rescore(rows: list[RunRow]) -> list[RunRow]:
    """依現行 scoring.py 的算法，用已存下來的檢索／回答內容重算所有分數。"""
    for r in rows:
        r.retrieval_hit = False
        r.retrieval_rank = None
        for rank, title in enumerate(r.retrieved_titles, start=1):
            if scoring.same_document(title, r.expected_source):
                r.retrieval_hit = True
                r.retrieval_rank = rank
                break
        if r.answered is None:
            continue
        r.citation_hit = scoring.hit_expected_source(r.cited_titles, r.expected_source)
        r.coverage = round(scoring.coverage(r.answer, r.reference), 4)
        r.f1 = round(scoring.f1(r.answer, r.reference), 4)
    return rows


def summarize(rows: list[RunRow]) -> dict:
    """把逐題結果彙總成可以拿來比門檻的指標。"""
    n = len(rows)
    ran_llm = [r for r in rows if r.answered is not None]
    answered = [r for r in ran_llm if not r.escalated]
    scored = [r for r in answered if r.coverage is not None]
    # 題庫預設每題都答得出來（有標註來源文件）；標了「應轉介」的題另外算。
    should_answer = [r for r in ran_llm if not r.expect_escalation]
    should_escalate = [r for r in ran_llm if r.expect_escalation]

    def rate(k: int, d: int) -> float:
        return k / d if d else 0.0

    return {
        "total": n,
        "retrieval_hits": sum(1 for r in rows if r.retrieval_hit),
        "retrieval_recall": rate(sum(1 for r in rows if r.retrieval_hit), n),
        "llm_ran": len(ran_llm),
        "escalated": sum(1 for r in ran_llm if r.escalated),
        "escalation_rate": rate(sum(1 for r in ran_llm if r.escalated), len(ran_llm)),
        # 誤轉介：答得出來卻轉介（洗版個管師清單）
        "false_escalation_rate": rate(
            sum(1 for r in should_answer if r.escalated), len(should_answer)
        ),
        # 漏轉：該轉介卻自己答了（醫療風險）；題庫沒標「應轉介」時為 None
        "escalation_recall": (
            rate(sum(1 for r in should_escalate if r.escalated), len(should_escalate))
            if should_escalate
            else None
        ),
        "citation_rate": rate(sum(1 for r in answered if r.has_citation), len(answered)),
        "citation_accuracy": rate(sum(1 for r in answered if r.citation_hit), len(answered)),
        "avg_coverage": rate(sum(r.coverage for r in scored), len(scored)),
        "avg_f1": rate(sum(r.f1 for r in scored), len(scored)),
        "errors": sum(1 for r in rows if r.error),
        "retrieval_errors": sum(1 for r in rows if r.retrieval_error),
        "answer_errors": sum(1 for r in rows if r.answer_error),
        "total_seconds": round(sum(r.elapsed for r in rows), 1),
    }
