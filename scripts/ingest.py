"""批次匯入：把 data/docs/ 底下所有 .txt/.md/.pdf 一次全部切塊入庫。

用法：python -m scripts.ingest
"""
import sys
from pathlib import Path

# 讓這支腳本可以直接以 `python -m scripts.ingest` 執行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, store          # noqa: E402
from app.extract import extract_text   # noqa: E402


def main():
    files = [
        p
        for p in config.DOCS_DIR.iterdir()
        if p.suffix.lower() in {".txt", ".md", ".pdf"}
    ]
    if not files:
        print(f"在 {config.DOCS_DIR} 找不到任何 .txt/.md/.pdf 檔。")
        return

    for path in files:
        raw = path.read_bytes()
        text = extract_text(path.name, raw)
        if not text.strip():
            print(f"[略過] {path.name}：擷取不到文字")
            continue
        n = store.add_document(doc_id=path.name, title=path.stem, text=text)
        print(f"[入庫] {path.name} → {n} 個片段")

    print("\n完成。目前知識庫文件：")
    for d in store.list_documents():
        print(f"  - {d['title']}（{d['chunks']} 片段）")


if __name__ == "__main__":
    main()
