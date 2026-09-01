"""FastAPI 後端：衛教問答 MVP。

端點：
  GET  /health        健康檢查
  POST /ingest        上傳一份衛教文件（.txt/.md/.pdf）→ 切塊入庫
  GET  /documents     列出目前知識庫中的文件
  POST /ask           病人提問 → 檢索 + LLM 作答（附出處）；答不了則轉介
  GET  /escalations   列出待個管師處理的問題清單

啟動：uvicorn app.main:app --reload
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import escalations, llm, store
from .extract import extract_text

app = FastAPI(title="TCA 衛教問答 MVP", version="0.1.0")


class AskRequest(BaseModel):
    question: str


class Citation(BaseModel):
    n: int
    title: str | None
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    can_answer: bool
    escalated: bool
    citations: list[Citation]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest")
async def ingest(file: UploadFile = File(...), title: str | None = Form(None)):
    raw = await file.read()
    text = extract_text(file.filename, raw)
    if not text.strip():
        raise HTTPException(status_code=400, detail="無法從檔案擷取到文字內容")

    doc_id = file.filename or str(uuid.uuid4())
    doc_title = title or file.filename or doc_id
    n_chunks = store.add_document(doc_id, doc_title, text)
    return {"doc_id": doc_id, "title": doc_title, "chunks": n_chunks}


@app.get("/documents")
def documents():
    return {"items": store.list_documents()}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="問題不可為空")

    hits = store.query(question)
    result = llm.answer_question(question, hits)

    escalated = False
    if not result.can_answer:
        escalations.add_escalation(question)
        escalated = True

    citations = []
    for idx in result.sources_used:
        if 1 <= idx <= len(hits):
            h = hits[idx - 1]
            citations.append(Citation(n=idx, title=h["title"], excerpt=h["text"][:200]))

    return AskResponse(
        answer=result.answer,
        can_answer=result.can_answer,
        escalated=escalated,
        citations=citations,
    )


@app.get("/escalations")
def get_escalations():
    return {"items": escalations.list_escalations()}
