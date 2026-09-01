# TCA 個案管理 RAG — 衛教問答 MVP

個案管理系統的最小可行產品(MVP)。這一版**只做「衛教問答」**這一條完整迴圈,用來驗證整條 RAG 管線:

> 衛教文件進知識庫 → 檢索到對的段落 → Claude 生成「有根據、附出處」的回答 → 答不了就轉介個案管理師

評估分級、資源比對、生理數據紀錄等其他功能,**先不做**,等這一條驗證成功再擴充。

---

## 功能(MVP 範圍)

- 📄 **上傳衛教文件**:支援 `.txt` / `.md` / `.pdf`,自動切塊、向量化入庫。
- 💬 **問答**:病人/家屬提問,AI 只根據知識庫回答,並附上引用來源。
- 📋 **轉介清單**:AI 答不了(或超出衛教範圍)的問題,自動記錄給個案管理師。

## 技術架構

| 層 | 用的東西 |
|----|---------|
| LLM | Claude(預設 `claude-opus-5`,可改 `claude-sonnet-5`) |
| RAG | Chroma 向量庫(本機持久化,免部署)+ 多語系 embedding(支援繁中) |
| 後端 | FastAPI |
| 前端 | Streamlit |

```
app/
  config.py        # 設定與路徑
  extract.py       # 從 txt/md/pdf 擷取文字
  store.py         # 切塊、入庫、檢索(Chroma)
  llm.py           # Claude 問答 + 結構化輸出(能否回答/答案/出處)
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

### 2. 設定 API 金鑰

```bash
cp .env.example .env
# 編輯 .env,填入你的 ANTHROPIC_API_KEY
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
