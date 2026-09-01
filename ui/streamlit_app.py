"""簡易前端（Streamlit）：呼叫 FastAPI 後端，提供問答／上傳／轉介清單三個頁籤。

啟動（後端要先跑起來）：streamlit run ui/streamlit_app.py
"""
import os

import requests
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="TCA 衛教問答", page_icon="🩺")
st.title("🩺 衛教問答助理（MVP）")
st.caption("病人／家屬提問 → AI 依衛教知識庫回答並附出處；答不了自動轉介個案管理師。")

tab_ask, tab_upload, tab_escalation = st.tabs(["💬 問答", "📄 上傳衛教文件", "📋 轉介清單"])


with tab_ask:
    question = st.text_input("請輸入您的問題", placeholder="例如：糖尿病患者飲食要注意什麼？")
    if st.button("送出", type="primary") and question.strip():
        with st.spinner("查詢中…"):
            try:
                r = requests.post(f"{API}/ask", json={"question": question}, timeout=120)
                r.raise_for_status()
                data = r.json()
            except Exception as e:  # noqa: BLE001
                st.error(f"呼叫後端失敗：{e}")
                data = None

        if data:
            if data["escalated"]:
                st.warning("這個問題已為您轉介個案管理師處理。")
            st.markdown("### 回答")
            st.write(data["answer"])

            if data["citations"]:
                st.markdown("### 引用來源")
                for c in data["citations"]:
                    with st.expander(f"[{c['n']}] {c['title']}"):
                        st.write(c["excerpt"] + "…")


with tab_upload:
    st.write("上傳衛教單（支援 .txt / .md / .pdf）。同名檔案會覆蓋更新。")
    up = st.file_uploader("選擇檔案", type=["txt", "md", "pdf"])
    title = st.text_input("文件標題（可留空，預設用檔名）")
    if st.button("上傳入庫") and up is not None:
        with st.spinner("處理中…"):
            try:
                files = {"file": (up.name, up.getvalue())}
                form = {"title": title} if title.strip() else {}
                r = requests.post(f"{API}/ingest", files=files, data=form, timeout=300)
                r.raise_for_status()
                res = r.json()
                st.success(f"已入庫：{res['title']}（{res['chunks']} 個片段）")
            except Exception as e:  # noqa: BLE001
                st.error(f"上傳失敗：{e}")

    st.divider()
    st.write("**目前知識庫文件**")
    try:
        docs = requests.get(f"{API}/documents", timeout=30).json()["items"]
        if docs:
            st.table(docs)
        else:
            st.info("知識庫還是空的，先上傳一份衛教單吧。")
    except Exception as e:  # noqa: BLE001
        st.error(f"讀取文件清單失敗：{e}")


with tab_escalation:
    st.write("以下是 AI 無法回答、已轉介給個案管理師的問題：")
    try:
        items = requests.get(f"{API}/escalations", timeout=30).json()["items"]
        if items:
            st.table(items)
        else:
            st.info("目前沒有待處理的轉介問題。")
    except Exception as e:  # noqa: BLE001
        st.error(f"讀取轉介清單失敗：{e}")
