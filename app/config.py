import os
from pathlib import Path

from dotenv import load_dotenv

# 讀取專案根目錄的 .env（若存在）
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = DATA_DIR / "docs"          # 放衛教單原始檔（.txt / .md / .pdf）
CHROMA_DIR = DATA_DIR / "chroma"      # 向量庫持久化目錄
ESCALATION_FILE = DATA_DIR / "escalations.jsonl"  # 轉介個管師的問題清單

# --- 模型 ---
# LLM 供應商：
#   "local"  → 本地端「OpenAI 相容」推論伺服器（預設，例如 Ollama）；免 API 金鑰、資料不出機房
#   "openai" → 雲端 OpenAI API（需 OPENAI_API_KEY）
# 未來換更強的本地模型，只要改 LLM_MODEL（見下）即可，程式不用動。
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local").strip().lower()

# 本地端推論伺服器位址（OpenAI 相容 API）。Ollama 預設就是這個。
# 換 llama.cpp / LM Studio / vLLM 也只要改這行。
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")

# 模型名稱（需先 `ollama pull <模型>`）：
#   local 預設用 TAIDE v2.0（Llama-3.1-TAIDE-LX-8B-Chat）——台灣國科會 TAIDE 計畫開發，
#     專為台灣繁體中文的用詞與語感調校，最適合「直接面對病人的衛教問答」；且可完全離線，
#     病歷等敏感資料不出機房。想要泛用能力更強可改成 qwen2.5:14b / qwen2.5:32b。
#   openai → 例如 gpt-4o-mini、gpt-4o
_DEFAULT_MODEL = (
    "hf.co/tetf/Llama-3.1-TAIDE-LX-8B-Chat-GGUF:Q8_0"
    if LLM_PROVIDER == "local"
    else "gpt-4o-mini"
)
LLM_MODEL = os.getenv("LLM_MODEL", _DEFAULT_MODEL)

# API 金鑰：雲端要填真金鑰；本地端不驗證，隨便給個非空字串即可。
# 同時接受標準的 OPENAI_API_KEY 或 .env 內小寫的 openai。
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("openai")
LLM_API_KEY = OPENAI_API_KEY or "ollama"

# 生成溫度：衛教問答要穩定、少發散，用偏低的值。
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# Embedding 仍用本機多語系模型（免 API、支援繁中）
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# --- RAG 參數 ---
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "health_education")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "450"))       # 每段文字大約幾個字
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))  # 段落間重疊字數
TOP_K = int(os.getenv("TOP_K", "4"))                   # 每次檢索取回幾段

# 確保資料目錄存在
for _d in (DATA_DIR, DOCS_DIR, CHROMA_DIR):
    _d.mkdir(parents=True, exist_ok=True)
