"""評測題庫（data/eval/eval_questions.csv）的載入與欄位對應。

只用標準函式庫，不 import app/*，這樣「題庫健檢」在還沒安裝向量庫／模型的機器上
也能跑（例如 CI 只做靜態檢查時）。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV = BASE_DIR / "data" / "eval" / "eval_questions.csv"
DOCS_DIR = BASE_DIR / "data" / "docs"

# 題庫是人手維護的中文 CSV，欄位標題可能微調（「答案」vs「參考答案（標準答案）」），
# 因此用關鍵字容錯比對，而不是寫死欄位順序。
_COLUMN_KEYS = {
    "id": ("題號", "序號"),
    "topic": ("主題",),
    "question": ("問題", "題目"),
    "reference": ("參考", "標準答案", "答案"),
    "source": ("來源文件", "來源", "出處"),
    "page": ("頁碼", "頁次"),
    # 保留欄位：題庫日後補「該不該轉介」的題目時（見 note.md 待討論議題），
    # 填「是/否」即可，測試會自動改用這欄判斷預期行為。
    "expect_escalation": ("應轉介", "預期轉介", "該轉介"),
}

_TRUE_WORDS = {"是", "y", "yes", "true", "1", "應轉介", "轉介"}


@dataclass(frozen=True)
class EvalQuestion:
    """題庫中的一題。"""

    qid: str            # 題號／序號
    topic: str          # 衛教主題
    question: str       # 病人／家屬的提問
    reference: str      # 參考答案（標準答案）
    source: str         # 來源文件檔名，例如「衛教單-防噎.pdf」
    page: str           # 頁碼（僅供人工回查，測試不驗證）
    expect_escalation: bool | None  # 預期是否轉介；題庫沒這欄時為 None
    row_no: int         # 在 CSV 中的實際列號（含標題列），錯誤訊息用

    @property
    def source_stem(self) -> str:
        """來源文件去掉副檔名 —— 入庫時 title 用的是檔名主幹（見 scripts/ingest.py）。"""
        return Path(self.source).stem if self.source else ""


def _find_column(header: list[str], keys: tuple[str, ...]) -> int | None:
    for i, h in enumerate(header):
        if any(k in h for k in keys):
            return i
    return None


@lru_cache(maxsize=8)
def load_questions(path: Path | str = DEFAULT_CSV) -> tuple[EvalQuestion, ...]:
    """讀題庫 CSV，回傳 EvalQuestion 序列（空白列自動略過）。

    用 tuple + lru_cache：整個測試 session 只讀一次檔，且結果不可變、不怕被測試改到。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到題庫檔：{path}")

    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = [list(r) for r in csv.reader(f)]
    if not rows:
        raise ValueError(f"題庫檔是空的：{path}")

    header = [str(h or "").strip() for h in rows[0]]
    idx = {name: _find_column(header, keys) for name, keys in _COLUMN_KEYS.items()}
    if idx["question"] is None:
        raise ValueError(f"{path} 第一列找不到「問題」欄，實際欄位：{header}")

    def cell(row: list[str], name: str) -> str:
        i = idx[name]
        if i is None or i >= len(row):
            return ""
        return str(row[i]).strip()

    items: list[EvalQuestion] = []
    for n, row in enumerate(rows[1:], start=2):  # start=2：CSV 實際列號（第 1 列是標題）
        question = cell(row, "question")
        if not question:
            continue  # 空白列略過（範本常留白列）
        esc = cell(row, "expect_escalation")
        items.append(
            EvalQuestion(
                qid=cell(row, "id") or str(n - 1),
                topic=cell(row, "topic"),
                question=question,
                reference=cell(row, "reference"),
                source=cell(row, "source"),
                page=cell(row, "page"),
                expect_escalation=(esc.lower() in _TRUE_WORDS) if esc else None,
                row_no=n,
            )
        )
    return tuple(items)
