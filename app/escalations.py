"""轉介清單：AI 答不了的問題會記錄到一個 JSONL 檔，供個案管理師後續處理。

MVP 先用 JSONL 檔（每行一筆）保存，之後要換 DB 也很容易。
"""
from __future__ import annotations

import json
from datetime import datetime

from . import config


def add_escalation(question: str, reason: str = "AI 無法從知識庫回答") -> dict:
    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "question": question,
        "reason": reason,
        "status": "pending",
    }
    with open(config.ESCALATION_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_escalations() -> list[dict]:
    if not config.ESCALATION_FILE.exists():
        return []
    items = []
    with open(config.ESCALATION_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    # 最新的排前面
    return list(reversed(items))
