
# TCA 個案管理 RAG — 衛教問答 MVP

個案管理系統的最小可行產品(MVP)。這一版**只做「衛教問答」**這一條完整迴圈,用來驗證整條 RAG 管線:

> 衛教文件進知識庫 → 檢索到對的段落 → LLM 生成「有根據、附出處」的回答 → 答不了就轉介個案管理師

評估分級、資源比對、生理數據紀錄等其他功能,**先不做**,等這一條驗證成功再擴充。

---

## 功能(MVP 範圍)

- 📄 **上傳衛教文件**:支援 `.txt` / `.md` / `.pdf`,自動切塊、向量化入庫。
- 💬 **問答**:病人/家屬提問,AI 只根據知識庫回答,並附上引用來源。
- 📋 **轉介清單**:AI 答不了(或超出衛教範圍)的問題,自動記錄給個案管理師。

## 技術架構

| 層   | 用的東西                                                                                                                                                               |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LLM  | **本地端(預設)**:Ollama 跑 **TAIDE v2.0**(台灣國科會、專為台灣繁中調校);**或**雲端 OpenAI(`gpt-4o-mini`)。用 `.env` 的 `LLM_PROVIDER` 一鍵切換 |
| RAG  | Chroma 向量庫(本機持久化,免部署)+ 多語系 embedding(支援繁中)                                                                                                           |
| 後端 | FastAPI                                                                                                                                                                |
| 前端 | Streamlit                                                                                                                                                              |

> 💡 **關於本地 vs 雲端 LLM**:embedding(檢索)本來就在本地跑,免 API。LLM 這層現在也預設走本地端(Ollama),整條管線可**完全離線、資料不出機房**——適合病歷等敏感資料。未來換更強的本地模型,只要改 `.env` 的 `LLM_MODEL`,程式不用動。

```
app/
  config.py        # 設定與路徑
  extract.py       # 從 txt/md/pdf 擷取文字
  store.py         # 切塊、入庫、檢索(Chroma)
  llm.py           # OpenAI 問答 + 結構化輸出(能否回答/答案/出處)
  escalations.py   # 轉介清單(JSONL)
  main.py          # FastAPI 端點
ui/
  streamlit_app.py # 簡易前端
scripts/
  ingest.py             # 批次匯入 data/docs/ 內所有文件
  make_eval_template.py # 產生評測題庫空白範本
  run_eval.py           # 跑題庫,輸出給個管師人工打分的 Excel
tests/                  # 自動化測試(pytest);不需人工打分,見下方「自動化測試」
  dataset.py            # 讀題庫 CSV
  scoring.py            # 自動評分(字元 bigram 覆蓋率、來源比對)
  runner.py             # 跑「檢索 → 作答」並收集結果
  report.py             # 輸出 HTML/JSON 報表
data/
  docs/                 # 放衛教單原始檔(附一份糖尿病範例)
  eval/                 # 題庫 CSV 與評測結果
```

---

## 快速開始

### 1. 安裝

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 設定 LLM

```bash
cp .env
```

**(A) 本地端 LLM(預設,推薦)** — 資料不出機房、免 API 金鑰:

```bash
# 1) 安裝 Ollama:https://ollama.com/download
# 2) 下載 TAIDE v2.0(台灣繁中專用,適合衛教問答的在地語感):
ollama pull hf.co/tetf/Llama-3.1-TAIDE-LX-8B-Chat-GGUF:Q8_0
```

`.env` 保持預設即可(`LLM_PROVIDER=local`)。
Ollama 會在 `http://localhost:11434` 常駐,程式透過 OpenAI 相容 API 呼叫它。

> **為什麼選 TAIDE v2.0?** 國科會 TAIDE 計畫開發、基於 Llama 3.1-8B,專為台灣繁中的用詞與語感調校(例:品質 vs 質量)。衛教是直接對病人講話的場景,在地語感很重要。想要泛用能力更強可改用 Qwen:`ollama pull qwen2.5:14b` 並把 `.env` 的 `LLM_MODEL` 改成 `qwen2.5:14b`。

**(B) 雲端 OpenAI** — 想用雲端時,編輯 `.env`:

```
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-你的金鑰
```

### 3. 匯入範例衛教單(或放你自己的檔到 data/docs/)

```bash
python -m scripts.ingest
```

> 第一次會自動下載 embedding 模型(約 470MB),請耐心等候。

### 4. 啟動後端

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
# API 文件:http://localhost:8000/docs
```

> 前後端都在同一台跑,後端綁 `127.0.0.1` 即可(前端也在同機,`localhost:8000` 對它就是本機)。要從外部直連後端才需要 `--host 0.0.0.0`,但一般建議走上面的 SSH 埠轉發、不要對外開埠。

### 5. 啟動前端(另開一個終端機)

```bash
streamlit run ui/streamlit_app.py
# 瀏覽器開 http://localhost:8501
```

---

## 在遠端主機執行、從本機瀏覽器存取(SSH 埠轉發)

把程式跑在遠端主機(例如校園/機房 PC),在自己筆電的瀏覽器操作前端時,常會遇到:

> 瀏覽器直接開 `http://<遠端IP>:8501` → **連不上 / 連線被拒絕**

**這通常不是程式壞了,而是防火牆/代理擋掉了對外埠。** 校園網、公司 Zscaler 之類的環境往往只放行 SSH(22 埠),不放行 8501/8000。Streamlit 本身有正常監聽(綁在 `0.0.0.0:8501`),只是外部連不進去。

**解法:走已經通的 SSH 連線,把埠「轉發」到本機,繞過防火牆。**

### 方法 A(推薦)— VS Code Remote-SSH 埠轉發

若你是用 VS Code Remote-SSH 連遠端:

1. 下方面板點 **「連接埠 / PORTS」** 頁籤(在 TERMINAL 旁邊)。
2. 按 **Forward a Port**,輸入 `8501`。
3. 點它產生的 `localhost:8501` 連結,或本機瀏覽器直接開 `http://localhost:8501`。

VS Code 會透過 SSH 把流量導過去,防火牆不用動任何設定。

### 方法 B — 手動 SSH 通道(在「本機」終端機執行)

```bash
ssh -L 8501:localhost:8501 -L 8000:localhost:8000 <使用者>@<遠端IP>
```

連上後,本機瀏覽器開 `http://localhost:8501`。

> ⚠️ 轉發後你開的是 **`localhost:8501`**,不是 `<遠端IP>:8501`。重點是流量走 SSH。

### 注意事項

- **後端也要在遠端啟動**:前端會去打 `http://localhost:8000`,若後端(uvicorn)沒開,一按送出/上傳就會報「呼叫後端失敗」。前後端都在遠端跑,所以後端只需在遠端起來即可,不強制轉發 8000(想在本機看 `/docs` 才需順便轉發 8000)。
- **HuggingFace / 模型下載都發生在遠端**:embedding 模型與 Ollama 抓模型都在遠端執行。只要**全部在遠端跑、本機只透過埠轉發看畫面**,本機能不能連 HuggingFace 完全不影響。若本機的網路擋 HuggingFace,不用理它——別在本機跑 `ingest`/模型即可。

---

## 快速驗證(不開前端也能測)

```bash
# 問一個知識庫答得出來的問題
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "糖尿病飲食要注意什麼?"}'

# 問一個超出衛教範圍的問題 → 應該會轉介
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "我的胰島素劑量該調成多少?"}'

# 看轉介清單
curl http://localhost:8000/escalations
```

---

## 自動化測試(tests/)

`scripts/run_eval.py` 是「跑一輪,輸出 Excel 給個管師人工打分」;`tests/` 則是**不需要人工打分**的自動化測試,吃的是同一份題庫 `data/eval/eval_questions.csv`,用來擋「改壞了卻沒發現」的退步。

兩者互補:自動化測試守**機械可驗**的性質(有沒有撈到對的衛教單、有沒有附出處、該不該轉介);**醫療正確性**仍由個案管理師用 Excel 複核。

### 三層,缺什麼就跳過什麼

| 層             | 測什麼                              | 需要                   | 指令                                      | 耗時    |
| -------------- | ----------------------------------- | ---------------------- | ----------------------------------------- | ------- |
| 題庫健檢＋單元 | 題庫欄位、來源檔存在、JSON 容錯解析 | 什麼都不用             | `python -m pytest -m "unit or dataset"` | 約 1 秒 |
| 檢索           | 有沒有撈到題庫標註的那份衛教單      | 已 ingest 的向量庫     | `python -m pytest -m retrieval`         | 數十秒  |
| 端到端         | 答不答得出來、附不附出處、轉不轉介  | Ollama(或 OpenAI 金鑰) | `python -m pytest --e2e`                | 5~30 分 |

環境沒準備好不會噴 traceback,而是 skip 並直接告訴你要跑哪一行指令(例如「請先執行 python -m scripts.ingest」「請執行 ollama pull ...」)。

### 常用指令

```bash
python -m pytest                          # 預設:題庫健檢＋單元＋檢索(不呼叫 LLM)
python -m pytest --e2e --limit 5          # 端到端先試跑 5 題,確認接得起來
python -m pytest --e2e                    # 完整跑 50 題
python -m pytest -m gate --e2e            # CI 用:只跑驗收門檻,看整體達不達標
python -m pytest --from-json=data/eval/auto_test_xxx.json   # 用上次的結果重算,不再呼叫模型
```

> 帶路徑的選項請用 `--from-json=路徑` 這種**等號寫法**;寫成空白分隔時 pytest 會把路徑誤認成測試目錄。

### 自動算的指標與門檻

| 指標           | 意思                                     | 門檻選項                    | 預設 |
| -------------- | ---------------------------------------- | --------------------------- | ---- |
| 檢索命中率     | 題庫標註的來源文件有出現在 top-k         | `--min-retrieval-recall`  | 0.85 |
| 誤轉介率       | 衛教單答得出來卻轉給個管師(洗版待辦清單) | `--max-escalation-rate`   | 0.20 |
| 回答附出處比例 | 有回答的題目中,附了引用的比例            | `--min-citation-rate`     | 0.80 |
| 引用文件正確率 | 引用到的就是題庫標註的那份衛教單         | `--min-citation-accuracy` | 0.70 |
| 平均覆蓋率     | 標準答案的重點有沒有被講到(粗篩答非所問) | `--min-coverage`          | 0.35 |
| 漏轉題數       | 該轉介卻自己亂答(轉介探針,見下)          | 固定為 0                    | 0    |

**覆蓋率是用字元 bigram 比對算的,只能抓「答非所問」,不等於醫療正確性。**
門檻預設值是初值,**第一次跑完請照實測數字校準**(例如實測誤轉介率 30%,就先把門檻訂在 0.30 擋住退步,再想辦法往下壓)。

轉介判斷兩個方向都測:

- **誤轉介**(不該轉卻轉)——題庫 50 題都測。這正是 `note.md` 記的那個待討論問題,現在變成可量化的數字。
- **漏轉**(該轉卻自己答)——`tests/test_escalation.py` 用 4 題探針,題目只取 `app/llm.py` 提示詞裡**明文寫死**的轉介情境(調劑量、判讀檢驗值、診斷、急救)。爭議中的「特定食物可不可以吃」刻意不放,等團隊拍板後在題庫 CSV 加一欄「應轉介」填是/否,測試會自動納入。

### 報表

每次跑完會在 `data/eval/` 產生兩個檔:

- `auto_test_<模型>_<時間>.html` — 瀏覽器直接開,含總覽、門檻對照、分主題統計、逐題明細(檢索未命中/被轉介/出錯的列標紅底)
- `auto_test_<模型>_<時間>.json` — 同一份資料的機器可讀版,可用 `--from-json=` 重算,或拿來比較不同模型的分數

測試走的是和 `/ask` 相同的路徑(`store.query` → `llm.answer_question`),但**不會寫入** `data/escalations.jsonl`,不會污染正式轉介清單。

---

## 怎麼算 MVP 驗證成功

抽 30~50 題常見衛教問題,由個案管理師判定:

- **準確率**:答對且有依據的比例(目標可先設 ≥ 80%)
- **轉介判斷**:該轉真人時有沒有正確轉介(不亂答)
- **有用性**:個管師/病人覺得省時、願意用

驗證成功 → 再依序擴充:評估分級 → 資源比對 → 生理數據紀錄。
