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
cp .env.example .env
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
uvicorn app.main:app --reload
# API 文件:http://localhost:8000/docs
```

### 5. 啟動前端(另開一個終端機)

```bash
streamlit run ui/streamlit_app.py
# 瀏覽器開 http://localhost:8501
```

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
