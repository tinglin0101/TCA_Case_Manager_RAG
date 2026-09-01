"""把自動化測試的結果寫成「可直接用瀏覽器打開」的 HTML 報表 + 一份 JSON。

HTML 是單一檔案、CSS 全部 inline、不連任何外部 CDN，離線也能開。
JSON 給程式用：可用 --from-json 重跑評分，或拿來比較不同模型／不同版本的分數。
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from .runner import RunRow, summarize

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin:0; padding:32px; background:#f4f6f9; color:#1c2430;
       font-family:"Microsoft JhengHei","PingFang TC","Noto Sans TC",system-ui,sans-serif; }
.wrap { max-width:1180px; margin:0 auto; }
h1 { font-size:24px; margin:0 0 4px; }
h2 { font-size:17px; margin:32px 0 10px; padding-left:9px; border-left:4px solid #2f5597; }
.sub { color:#5b6875; font-size:13px; margin-bottom:20px; }
.meta { background:#fff; border:1px solid #dde3ea; border-radius:8px; padding:14px 18px;
        font-size:13px; display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:6px 24px; }
.meta b { color:#5b6875; font-weight:600; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-top:12px; }
.card { background:#fff; border:1px solid #dde3ea; border-radius:8px; padding:14px 16px; }
.card .k { font-size:12px; color:#5b6875; }
.card .v { font-size:26px; font-weight:700; margin-top:4px; letter-spacing:-.5px; }
.card.ok .v { color:#1a7f4b; }
.card.bad .v { color:#c0392b; }
.card.warn .v { color:#b26a00; }
table { width:100%; border-collapse:collapse; background:#fff; font-size:13px;
        border:1px solid #dde3ea; border-radius:8px; overflow:hidden; }
th, td { padding:9px 11px; text-align:left; border-bottom:1px solid #edf1f5; vertical-align:top; }
th { background:#2f5597; color:#fff; font-weight:600; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
tr.miss { background:#fff6f6; }
td.num { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
.badge { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px; white-space:nowrap; }
.badge.ok { background:#e3f6ec; color:#1a7f4b; }
.badge.bad { background:#fdecea; color:#c0392b; }
.badge.mut { background:#eef1f5; color:#5b6875; }
.q { font-weight:600; }
.ans { color:#33404f; white-space:pre-wrap; }
.ref { color:#5b6875; white-space:pre-wrap; font-size:12px; }
.scroll { overflow-x:auto; }
details summary { cursor:pointer; color:#2f5597; font-size:12px; }
.foot { margin-top:28px; color:#7b8794; font-size:12px; line-height:1.8; }
"""


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _card(label: str, value: str, tone: str = "") -> str:
    return (
        f'<div class="card {tone}"><div class="k">{_esc(label)}</div>'
        f'<div class="v">{_esc(value)}</div></div>'
    )


def _topic_table(rows: list[RunRow]) -> str:
    """分主題統計：哪個衛教主題特別容易檢索不到或被轉介，一眼看出來。"""
    topics: list[str] = []
    for r in rows:
        t = r.topic or "（未分類）"
        if t not in topics:
            topics.append(t)

    body = []
    for t in topics:
        sub = [r for r in rows if (r.topic or "（未分類）") == t]
        ran = [r for r in sub if r.answered is not None]
        hit = sum(1 for r in sub if r.retrieval_hit)
        esc = sum(1 for r in ran if r.escalated)
        cov = [r.coverage for r in ran if r.coverage is not None and not r.escalated]

        hit_cell = f"{hit}／{len(sub)}（{hit / len(sub) * 100:.0f}%）" if sub else "—"
        esc_cell = f"{esc}／{len(ran)}（{esc / len(ran) * 100:.0f}%）" if ran else "—"
        cov_cell = f"{sum(cov) / len(cov) * 100:.0f}%" if cov else "—"

        body.append(
            "<tr>"
            f"<td>{_esc(t)}</td>"
            f'<td class="num">{len(sub)}</td>'
            f'<td class="num">{hit_cell}</td>'
            f'<td class="num">{esc_cell}</td>'
            f'<td class="num">{cov_cell}</td>'
            "</tr>"
        )

    return (
        '<div class="scroll"><table><thead><tr>'
        "<th>衛教主題</th><th>題數</th><th>檢索命中</th><th>模型轉介</th><th>平均覆蓋率</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def _gate_table(gates: list[dict]) -> str:
    """驗收門檻對照表；gates 由 conftest 收集（每個 gate 測試跑完會登記一筆）。"""
    if not gates:
        return '<p class="sub">（這次沒有跑到門檻檢核；用 <code>pytest -m gate</code> 只跑門檻）</p>'

    body = []
    for g in gates:
        badge = (
            '<span class="badge ok">通過</span>'
            if g.get("passed")
            else '<span class="badge bad">未達標</span>'
        )
        body.append(
            "<tr>"
            f"<td>{_esc(g['name'])}</td>"
            f'<td class="num">{_esc(g["actual"])}</td>'
            f'<td class="num">{_esc(g["threshold"])}</td>'
            f"<td>{badge}</td>"
            "</tr>"
        )
    return (
        '<div class="scroll"><table><thead><tr>'
        "<th>驗收指標</th><th>實際</th><th>門檻</th><th>結果</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def _detail_row(r: RunRow, ran_llm: bool) -> str:
    miss = (not r.retrieval_hit) or r.escalated or bool(r.error)

    if r.retrieval_hit:
        retrieval = f'<span class="badge ok">命中 第{r.retrieval_rank}名</span>'
    else:
        retrieval = '<span class="badge bad">未命中</span>'
    titles = "、".join(dict.fromkeys(t for t in r.retrieved_titles if t)) or "（無）"
    retrieval += f'<div class="ref">檢索到：{_esc(titles)}</div>'

    cells = (
        f'<td class="num">{_esc(r.qid)}</td>'
        f"<td>{_esc(r.topic)}</td>"
        f'<td><div class="q">{_esc(r.question)}</div>'
        f'<div class="ref">標註來源：{_esc(r.expected_source)}</div></td>'
        f"<td>{retrieval}</td>"
    )

    if ran_llm:
        if r.error:
            verdict = f'<span class="badge bad">執行錯誤</span><div class="ref">{_esc(r.error)}</div>'
        elif r.answered is None:
            verdict = '<span class="badge mut">未跑</span>'
        elif r.escalated:
            verdict = '<span class="badge bad">轉介個管師</span>'
        else:
            tone = "ok" if r.citation_hit else ("mut" if r.has_citation else "bad")
            label = "引用正確" if r.citation_hit else ("引用他篇" if r.has_citation else "無引用")
            verdict = f'<span class="badge ok">已回答</span> <span class="badge {tone}">{label}</span>'

        answer_cell = (
            f'<div class="ans">{_esc(r.answer) or "—"}</div>'
            f"<details><summary>參考答案</summary>"
            f'<div class="ref">{_esc(r.reference)}</div></details>'
        )
        cells += (
            f"<td>{verdict}</td>"
            f'<td class="num">{_pct(r.coverage)}</td>'
            f"<td>{answer_cell}</td>"
        )

    return f'<tr class="{"miss" if miss else ""}">{cells}</tr>'


def _detail_table(rows: list[RunRow], ran_llm: bool) -> str:
    head = "<th>題號</th><th>主題</th><th>問題</th><th>檢索</th>"
    if ran_llm:
        head += "<th>模型判定</th><th>覆蓋率</th><th>模型回答</th>"
    body = "".join(_detail_row(r, ran_llm) for r in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def build_html(rows: list[RunRow], meta: dict, gates: list[dict]) -> str:
    s = summarize(rows)
    ran_llm = s["llm_ran"] > 0

    cards = [
        _card("題數", str(s["total"])),
        _card(
            "檢索命中率",
            _pct(s["retrieval_recall"]),
            "ok" if s["retrieval_recall"] >= 0.9 else "warn",
        ),
    ]
    if ran_llm:
        cards += [
            _card("模型轉介率", _pct(s["escalation_rate"]), "bad" if s["escalation_rate"] > 0.2 else "ok"),
            _card("引用文件正確率", _pct(s["citation_accuracy"]), "ok" if s["citation_accuracy"] >= 0.8 else "warn"),
            _card("平均覆蓋率", _pct(s["avg_coverage"])),
            _card("執行錯誤", str(s["errors"]), "bad" if s["errors"] else "ok"),
        ]

    meta_html = "".join(f"<div><b>{_esc(k)}</b>　{_esc(v)}</div>" for k, v in meta.items())

    verdict = ""
    if gates:
        verdict = (
            '<span class="badge ok">全部門檻通過</span>'
            if all(g.get("passed") for g in gates)
            else '<span class="badge bad">有門檻未達標</span>'
        )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>衛教問答 自動化測試報告</title>
<style>{_CSS}</style>
</head>
<body><div class="wrap">
  <h1>衛教問答 自動化測試報告 {verdict}</h1>
  <div class="sub">題庫逐題跑過「檢索 → LLM 作答」後自動評分。這裡的分數用來擋退步，
    最終醫療正確性仍由個案管理師人工複核（scripts/run_eval.py 產生的 Excel）。</div>
  <div class="meta">{meta_html}</div>

  <h2>總覽</h2>
  <div class="cards">{"".join(cards)}</div>

  <h2>驗收門檻</h2>
  {_gate_table(gates)}

  <h2>分主題</h2>
  {_topic_table(rows)}

  <h2>逐題明細</h2>
  {_detail_table(rows, ran_llm)}

  <div class="foot">
    「檢索命中」＝題庫標註的來源文件有出現在 top-k 檢索結果中。<br>
    「引用文件正確率」＝模型實際引用的來源，就是題庫標註的那份衛教單的比例。<br>
    「覆蓋率」＝標準答案的字元 bigram 有多少比例出現在模型回答中；用來偵測答非所問，
      <b>不等於醫療正確性</b>。<br>
    紅底列＝檢索未命中／被轉介／執行錯誤，優先看這幾題。
  </div>
</div></body></html>
"""


def write_report(rows: list[RunRow], meta: dict, gates: list[dict], out_dir: Path, stem: str) -> dict:
    """寫出 HTML + JSON 兩份報表，回傳檔案路徑。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / f"{stem}.html"
    json_path = out_dir / f"{stem}.json"

    html_path.write_text(build_html(rows, meta, gates), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "meta": meta,
                "summary": summarize(rows),
                "gates": gates,
                "rows": [r.to_dict() for r in rows],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"html": html_path, "json": json_path}
