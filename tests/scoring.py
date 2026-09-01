"""自動評分：不需要人工打分，也不需要再叫一個 LLM 當裁判。

為什麼用「字元 bigram」比對？
    中文沒有空白斷詞。若用關鍵字硬比對，模型只要換句話說（「不適合」vs「不建議」）
    就被判錯；若整段字串比對又太嚴。折衷做法是把兩段文字正規化成純中文字元序列後，
    比對相鄰字元對（bigram）—— 這是中文問答評測常用的 char-level F1（如 CMRC/DRCD），
    不需要斷詞套件，對同義改寫比關鍵字比對寬容，也抓得出「答非所問」。

    這層分數只用來擋「明顯答錯／答非所問」的退步，**不是**準確率的最終判準；
    最終準確率仍由個案管理師用 scripts/run_eval.py 產出的 Excel 打分。
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

# 只留中日韓漢字與英數，其餘（標點、空白、全形符號）視為雜訊丟掉。
_KEEP = re.compile(r"[0-9a-z\u3400-\u4dbf\u4e00-\u9fff]+")


def normalize(text: str) -> str:
    """正規化：全形轉半形、轉小寫、去除標點與空白，只留漢字與英數。"""
    if not text:
        return ""
    # NFKC 把全形數字／英文（２０００）轉成半形（2000），避免同義字被算成不同字元。
    text = unicodedata.normalize("NFKC", str(text)).lower()
    return "".join(_KEEP.findall(text))


def bigrams(text: str) -> Counter:
    """把正規化後的字元序列切成相鄰字元對；長度不足 2 時退回單字元。"""
    s = normalize(text)
    if not s:
        return Counter()
    if len(s) < 2:
        return Counter([s])
    return Counter(s[i : i + 2] for i in range(len(s) - 1))


def _overlap(pred: Counter, ref: Counter) -> int:
    """兩個 bigram 多重集合的交集大小。"""
    return sum((pred & ref).values())


def coverage(pred: str, ref: str) -> float:
    """覆蓋率（recall）：標準答案的內容有多少比例出現在模型回答裡。

    生成式回答通常比標準答案長，用 recall 比 F1 更貼近「重點有沒有講到」。
    """
    r = bigrams(ref)
    if not r:
        return 0.0
    return _overlap(bigrams(pred), r) / sum(r.values())


def f1(pred: str, ref: str) -> float:
    """字元 bigram F1：同時懲罰漏講重點與長篇廢話。"""
    p, r = bigrams(pred), bigrams(ref)
    if not p or not r:
        return 0.0
    hit = _overlap(p, r)
    if hit == 0:
        return 0.0
    precision = hit / sum(p.values())
    recall = hit / sum(r.values())
    return 2 * precision * recall / (precision + recall)


def same_document(title: str, expected: str) -> bool:
    """比對「檢索／引用到的文件標題」與題庫標註的來源文件是否為同一份。

    入庫時 title 用檔名主幹（scripts/ingest.py），題庫寫的是含副檔名的檔名，
    因此兩邊都正規化後再比；允許其中一方是另一方的前綴（檔名被截斷或加註版本時仍算命中）。
    """
    a, b = normalize(title), normalize(expected)
    # 題庫的「衛教單-防噎.pdf」正規化後會留下 pdf 尾巴，去掉再比。
    for suffix in ("pdf", "txt", "md"):
        if a.endswith(suffix) and len(a) > len(suffix):
            a = a[: -len(suffix)]
        if b.endswith(suffix) and len(b) > len(suffix):
            b = b[: -len(suffix)]
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def hit_expected_source(titles: list[str], expected: str) -> bool:
    """檢索／引用到的一組文件標題中，是否含有題庫標註的來源文件。"""
    return any(same_document(t or "", expected) for t in titles)
