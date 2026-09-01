"""pytest 共用設定：命令列選項、題庫載入、跑管線的 session 級 fixture、報表輸出。

分層設計（一層跑不動不會拖垮下一層，缺什麼就 skip 並說清楚要裝什麼）：
    1. 題庫健檢 / 純函式單元測試 —— 不需要向量庫、不需要模型，隨時可跑。
    2. 檢索測試 —— 需要已 ingest 的 Chroma 向量庫；整個 session 只跑一次檢索。
    3. 端到端作答測試 —— 需要 --e2e 且 LLM 服務可用；整個 session 只跑一次作答。

測試全程走 store.query → llm.answer_question（與 /ask 端點相同路徑），
但不呼叫 escalations.add_escalation，所以不會污染正式轉介清單。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from .dataset import DEFAULT_CSV, EvalQuestion, load_questions
from .report import write_report
from .runner import RunRow, load_rows, run_answers, run_retrieval, summarize

BASE_DIR = Path(__file__).resolve().parent.parent

# 整個 session 共用的狀態：跑過的逐題結果、達標檢核紀錄（給報表用）。
_ROWS: list[RunRow] = []
_GATES: list[dict] = []


# --------------------------------------------------------------------------- 選項
def pytest_addoption(parser):
    g = parser.getgroup("衛教問答評測")
    g.addoption("--e2e", action="store_true", default=False,
                help="開啟端到端測試：真的呼叫 LLM 逐題作答（慢，本地 8B 約 5-30 分鐘）")
    g.addoption("--questions", default=str(DEFAULT_CSV),
                help=f"題庫 CSV 路徑（預設 {DEFAULT_CSV.relative_to(BASE_DIR)}）")
    g.addoption("--limit", type=int, default=0,
                help="只跑前 N 題（0 = 全部）；先用 --limit 5 --e2e 試跑比較快")
    g.addoption("--from-json", default=None, dest="from_json",
                help="不呼叫模型，改讀先前跑出來的結果 JSON 重新評分（調門檻／看報表用）")
    g.addoption("--report-dir", default=str(BASE_DIR / "data" / "eval"),
                help="報表輸出目錄（預設 data/eval/）")
    g.addoption("--no-report", action="store_true", default=False, help="不要輸出 HTML/JSON 報表")

    # --- 驗收門檻（第一次跑完請依實測結果調整，見 README「自動化測試」）---
    g.addoption("--min-retrieval-recall", type=float, default=0.85,
                help="檢索命中率下限（題庫標註的來源文件有出現在 top-k）")
    g.addoption("--max-escalation-rate", type=float, default=0.20,
                help="誤轉介率上限：題庫 50 題都答得出來，被轉介就算誤轉")
    g.addoption("--min-coverage", type=float, default=0.35, help="平均參考答案覆蓋率下限")
    g.addoption("--min-item-coverage", type=float, default=0.15, help="單題覆蓋率下限（抓答非所問）")
    g.addoption("--min-citation-rate", type=float, default=0.80, help="有附出處的比例下限")
    g.addoption("--min-citation-accuracy", type=float, default=0.70, help="引用文件正確率下限")


def pytest_collection_modifyitems(config, items):
    """沒開 --e2e（也沒給 --from-json）時，直接跳過所有 e2e 測試。"""
    if config.getoption("e2e") or config.getoption("from_json"):
        return
    skip = pytest.mark.skip(reason="端到端測試預設不跑；加 --e2e 才會真的呼叫 LLM")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)


# --------------------------------------------------------------------------- 題庫
def _selected(config) -> tuple[EvalQuestion, ...]:
    """依 --questions / --limit 取出這次要測的題目。"""
    qs = load_questions(Path(config.getoption("questions")))
    limit = config.getoption("limit")
    return qs[:limit] if limit and limit > 0 else qs


def pytest_generate_tests(metafunc):
    """把題庫展開成一題一個測試案例（測試函式只要宣告 q 這個參數就會拿到）。"""
    if "q" in metafunc.fixturenames:
        try:
            qs = _selected(metafunc.config)
        except (FileNotFoundError, ValueError) as e:
            pytest.skip(f"題庫載入失敗：{e}")
            return
        # 題號當 id（不用中文，避免各家終端機編碼問題）；問題內容放在失敗訊息裡。
        metafunc.parametrize("q", qs, ids=[f"Q{x.qid}" for x in qs])


@pytest.fixture(scope="session")
def questions(pytestconfig) -> tuple[EvalQuestion, ...]:
    return _selected(pytestconfig)


# --------------------------------------------------------------------------- 環境檢查
def _log(config, msg: str) -> None:
    """把進度印在終端機上（即使沒有 -s 也看得到，跑 50 題時才不會像當機）。"""
    tr = config.pluginmanager.get_plugin("terminalreporter")
    if tr is not None:
        tr.write_line(msg)
    else:
        print(msg)


@pytest.fixture(scope="session")
def kb_ready(pytestconfig):
    """確認向量庫已匯入衛教單；沒有就 skip 並告訴使用者要跑哪個指令。"""
    if pytestconfig.getoption("from_json"):
        return []
    try:
        from app import store
    except ImportError as e:
        pytest.skip(f"缺少套件（{e}）；請先 pip install -r requirements.txt")
    try:
        docs = store.list_documents()
    except Exception as e:  # noqa: BLE001 — 向量庫壞掉時給明確指示，不要拋一堆 traceback
        pytest.skip(f"讀不到向量庫（{type(e).__name__}: {e}）；請先執行 python -m scripts.ingest")
    if not docs:
        pytest.skip("知識庫是空的；請先執行 python -m scripts.ingest 匯入 data/docs/ 的衛教單")
    return docs


@pytest.fixture(scope="session")
def llm_ready(pytestconfig):
    """確認 LLM 服務可用、且設定的模型真的存在（本地端最常見的坑就是忘記 ollama pull）。"""
    if pytestconfig.getoption("from_json"):
        return "from-json"
    from app import config as app_config
    from app import llm

    if app_config.LLM_PROVIDER != "local":
        if not app_config.OPENAI_API_KEY:
            pytest.skip("LLM_PROVIDER=openai 但沒有 OPENAI_API_KEY；請設定 .env")
        return app_config.LLM_MODEL

    try:
        available = [m.id for m in llm.get_client().models.list().data]
    except Exception as e:  # noqa: BLE001
        pytest.skip(
            f"連不上本地 LLM（{app_config.LLM_BASE_URL}）：{type(e).__name__}: {e}\n"
            "請確認 Ollama 已啟動（ollama serve）"
        )
    want = app_config.LLM_MODEL
    if not any(m == want or m.startswith(want) or want.startswith(m) for m in available):
        pytest.skip(
            f"本地端沒有模型「{want}」。已安裝：{'、'.join(available) or '（無）'}\n"
            f"請執行： ollama pull {want}　或改 .env 的 LLM_MODEL"
        )
    return want


# --------------------------------------------------------------------------- 跑管線
@pytest.fixture(scope="session")
def retrieval_rows(pytestconfig, questions, kb_ready) -> list[RunRow]:
    """整個 session 只跑一次檢索，所有檢索測試共用這批結果。"""
    if _ROWS:
        return _ROWS

    from_json = pytestconfig.getoption("from_json")
    if from_json:
        path = Path(from_json)
        if not path.exists():
            pytest.skip(f"找不到 --from-json 指定的檔案：{path}")
        rows = load_rows(path)
        _log(pytestconfig, f"\n[評測] 讀取既有結果：{path}（{len(rows)} 題，未呼叫模型）")
    else:
        _log(pytestconfig, f"\n[評測] 開始檢索 {len(questions)} 題……")
        rows = run_retrieval(questions, log=lambda m: _log(pytestconfig, "  " + m))

    _ROWS.extend(rows)
    return _ROWS


@pytest.fixture(scope="session")
def answer_rows(pytestconfig, retrieval_rows, llm_ready) -> list[RunRow]:
    """整個 session 只跑一次 LLM 作答（就地把答案補進 retrieval_rows）。"""
    if pytestconfig.getoption("from_json"):
        if all(r.answered is None for r in retrieval_rows):
            pytest.skip("--from-json 指定的結果檔沒有作答紀錄（只跑過檢索）")
        return retrieval_rows

    if all(r.answered is None for r in retrieval_rows):
        n = len(retrieval_rows)
        _log(pytestconfig, f"\n[評測] 開始逐題作答 {n} 題（本地模型較慢，請耐心等）……")
        run_answers(retrieval_rows, log=lambda m: _log(pytestconfig, "  " + m))
    return retrieval_rows


@pytest.fixture
def result_for(retrieval_rows):
    """依題號取回該題的執行結果。"""
    index = {r.qid: r for r in retrieval_rows}

    def _get(q: EvalQuestion) -> RunRow:
        row = index.get(q.qid)
        if row is None:
            pytest.skip(f"結果檔中找不到題號 {q.qid}（題庫與結果檔可能不同批）")
        return row

    return _get


@pytest.fixture
def answer_for(answer_rows):
    """依題號取回該題的作答結果（會確保 LLM 那輪已經跑過）。"""
    index = {r.qid: r for r in answer_rows}

    def _get(q: EvalQuestion) -> RunRow:
        row = index.get(q.qid)
        if row is None:
            pytest.skip(f"結果檔中找不到題號 {q.qid}")
        if row.answered is None:
            pytest.skip(f"題號 {q.qid} 這輪沒有作答紀錄（通常是檢索階段就失敗了）")
        return row

    return _get


@pytest.fixture
def retrieval_metrics(retrieval_rows) -> dict:
    return summarize(retrieval_rows)


@pytest.fixture
def answer_metrics(answer_rows) -> dict:
    return summarize(answer_rows)


# --------------------------------------------------------------------------- 門檻
def _fmt(value, kind: str) -> str:
    if kind == "pct":
        return f"{value * 100:.0f}%"
    if kind == "float":
        return f"{value:.2f}"
    return str(value)


@pytest.fixture
def gate():
    """驗收門檻檢核：登記一筆到報表，再用中文訊息斷言。

    用法： gate("檢索命中率", 0.92, ">=", 0.85)
    """
    def _check(name: str, actual: float, op: str, threshold: float,
               kind: str = "pct", detail: str = "") -> None:
        passed = actual >= threshold if op == ">=" else actual <= threshold
        _GATES.append({
            "name": name,
            "actual": _fmt(actual, kind),
            "threshold": f"{op} {_fmt(threshold, kind)}",
            "passed": passed,
        })
        msg = f"{name} = {_fmt(actual, kind)}，未達門檻（需 {op} {_fmt(threshold, kind)}）"
        if detail:
            msg += "\n" + detail
        assert passed, msg

    return _check


# --------------------------------------------------------------------------- 報表
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """測試跑完後，把逐題結果寫成 HTML + JSON 報表，並在終端機印出路徑。"""
    if not _ROWS or config.getoption("no_report"):
        return

    s = summarize(_ROWS)
    ran_llm = s["llm_ran"] > 0

    try:
        from app import config as app_config
        provider, model, top_k = app_config.LLM_PROVIDER, app_config.LLM_MODEL, app_config.TOP_K
    except Exception:  # noqa: BLE001
        provider, model, top_k = "-", "-", "-"

    meta = {
        "產生時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "題庫": str(Path(config.getoption("questions")).name),
        "題數": s["total"],
        "LLM 供應商": provider,
        "LLM 模型": model,
        "檢索 top_k": top_k,
        "本次是否呼叫模型": "否（--from-json 重新評分）" if config.getoption("from_json")
                            else ("是" if ran_llm else "否（只跑檢索）"),
        "總耗時": f"{s['total_seconds']} 秒",
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # 到秒：同一分鐘跑兩次不會互相覆蓋
    safe_model = str(model).split("/")[-1].replace(":", "_")
    stem = f"auto_test_{safe_model if ran_llm else 'retrieval'}_{stamp}"

    try:
        paths = write_report(_ROWS, meta, _GATES, Path(config.getoption("report_dir")), stem)
    except Exception as e:  # noqa: BLE001 — 報表寫失敗不該影響測試結果
        terminalreporter.write_line(f"[評測] 報表寫入失敗：{type(e).__name__}: {e}", yellow=True)
        return

    terminalreporter.write_sep("-", "評測報表")
    terminalreporter.write_line(f"HTML（用瀏覽器開）：{paths['html']}")
    terminalreporter.write_line(f"JSON（可 --from-json 重跑評分）：{paths['json']}")
    if ran_llm:
        terminalreporter.write_line(
            f"檢索命中率 {s['retrieval_recall']:.0%}｜轉介率 {s['escalation_rate']:.0%}｜"
            f"平均覆蓋率 {s['avg_coverage']:.0%}｜引用正確率 {s['citation_accuracy']:.0%}"
        )
    else:
        terminalreporter.write_line(f"檢索命中率 {s['retrieval_recall']:.0%}（本次未呼叫模型）")
