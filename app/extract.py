"""從上傳的檔案擷取純文字。MVP 先支援 .txt / .md / .pdf。"""
import io


def extract_text(filename: str, raw: bytes) -> str:
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)

    # .txt / .md / 其他可用 UTF-8 解碼的純文字
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="ignore")
