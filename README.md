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
  ingest.py        # 批次匯入 data/docs/ 內所有文件
data/
  docs/            # 放衛教單原始檔(附一份糖尿病範例)
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

## 怎麼算 MVP 驗證成功

抽 30~50 題常見衛教問題,由個案管理師判定:

- **準確率**:答對且有依據的比例(目標可先設 ≥ 80%)
- **轉介判斷**:該轉真人時有沒有正確轉介(不亂答)
- **有用性**:個管師/病人覺得省時、願意用

驗證成功 → 再依序擴充:評估分級 → 資源比對 → 生理數據紀錄。
