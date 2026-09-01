"""
測試 OpenAI API 是否可正常連線。

用法:
    pip install openai
    python test_openai.py

會從專案根目錄的 .env 讀取 API key（變數名稱為 openai）。
"""

import os
import sys
from pathlib import Path


def load_env(env_path: Path) -> None:
    """簡易的 .env 讀取器，把 KEY=VALUE 寫進 os.environ（不依賴 python-dotenv）。"""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_env(Path(__file__).resolve().parent / ".env")

    # .env 內的變數名稱是小寫的 openai，同時也接受標準的 OPENAI_API_KEY
    api_key = os.environ.get("openai") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ 找不到 API key，請確認 .env 內有 openai=<你的金鑰>")
        return 1

    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        print("❌ 尚未安裝 openai 套件，請先執行：pip install openai")
        return 1

    client = OpenAI(api_key=api_key)

    print("→ 正在呼叫 OpenAI API ...")
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是一個簡潔的助理。"},
                {"role": "user", "content": "請用一句話回覆：API 測試成功。"},
            ],
        )
    except Exception as e:  # 連線、驗證、額度等錯誤都會落到這裡
        print(f"❌ API 呼叫失敗：{type(e).__name__}: {e}")
        return 1

    print("✅ API 連線成功！")
    print("模型回覆：", resp.choices[0].message.content)
    if resp.usage:
        print(f"用量：prompt={resp.usage.prompt_tokens}, "
              f"completion={resp.usage.completion_tokens}, "
              f"total={resp.usage.total_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
