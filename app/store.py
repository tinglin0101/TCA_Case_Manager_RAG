"""向量庫：負責把衛教文件切塊、存進 Chroma，並依問題檢索最相關的段落。

用 Chroma 的本機持久化模式（免部署），embedding 用多語系模型（支援繁體中文），
不需要額外的 embedding API 金鑰。
"""
from __future__ import annotations

import chromadb
from chromadb.utils import embedding_functions

from . import config

_collection = None


def get_collection():
    """取得（或建立）Chroma collection，單例快取避免重複載入 embedding 模型。"""
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.EMBEDDING_MODEL
        )
        _collection = client.get_or_create_collection(
            name=config.COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    """段落感知的簡易切塊：先照段落貼合，太長的段落再硬切（含重疊）。"""
    size = size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""

    for p in paragraphs:
        if len(p) > size:
            # 先把目前累積的段落收掉
            if buf:
                chunks.append(buf)
                buf = ""
            # 過長段落硬切成有重疊的小段
            start = 0
            step = max(1, size - overlap)
            while start < len(p):
                chunks.append(p[start : start + size])
                start += step
        elif len(buf) + len(p) + 1 <= size:
            buf = (buf + "\n" + p).strip()
        else:
            if buf:
                chunks.append(buf)
            buf = p

    if buf:
        chunks.append(buf)
    return chunks


def add_document(doc_id: str, title: str, text: str) -> int:
    """把一份文件切塊後寫入向量庫。若同名文件已存在會先移除舊資料（可重複上傳更新）。"""
    collection = get_collection()
    collection.delete(where={"doc_id": doc_id})  # 覆蓋更新

    chunks = chunk_text(text)
    if not chunks:
        return 0

    ids = [f"{doc_id}::{i}" for i in range(len(chunks))]
    metadatas = [
        {"doc_id": doc_id, "title": title, "chunk_index": i}
        for i in range(len(chunks))
    ]
    collection.add(ids=ids, documents=chunks, metadatas=metadatas)
    return len(chunks)


def query(question: str, top_k: int = None) -> list[dict]:
    """依問題檢索最相關的段落，回傳含來源資訊的清單。"""
    top_k = top_k or config.TOP_K
    collection = get_collection()

    if collection.count() == 0:
        return []

    res = collection.query(query_texts=[question], n_results=top_k)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append(
            {
                "text": doc,
                "title": meta.get("title"),
                "doc_id": meta.get("doc_id"),
                "chunk_index": meta.get("chunk_index"),
                "distance": dist,
            }
        )
    return hits


def list_documents() -> list[dict]:
    """列出目前知識庫中有哪些文件、各自幾個 chunk。"""
    collection = get_collection()
    if collection.count() == 0:
        return []

    got = collection.get(include=["metadatas"])
    counts: dict[str, dict] = {}
    for meta in got.get("metadatas", []):
        doc_id = meta.get("doc_id")
        entry = counts.setdefault(doc_id, {"doc_id": doc_id, "title": meta.get("title"), "chunks": 0})
        entry["chunks"] += 1
    return list(counts.values())
