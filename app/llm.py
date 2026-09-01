"""LLM 問答層：把檢索到的段落當作唯一依據，產生「有根據、附出處」的回答，
並判斷這題能不能回答（不能回答就標記為需轉介個管師）。

支援兩種供應商（用環境變數 LLM_PROVIDER 切換，見 config.py）：
  - "local"  ：本地端「OpenAI 相容」推論伺服器（預設，例如 Ollama）。資料不出機房。
  - "openai" ：雲端 OpenAI API。

兩者都要求模型回傳固定的 JSON 結構（能否回答／答案／出處）方便後端處理：
  - OpenAI 用原生 Structured Outputs（response_format=Pydantic），最穩。
  - 本地模型用 JSON 模式 + 容錯解析；萬一解析失敗，安全起見一律轉介個管師（不亂答）。
"""
from __future__ import annotations

import json
import re
from typing import List

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from . import config

_client = None


def get_client() -> OpenAI:
    """單例 OpenAI client。本地端指向 LLM_BASE_URL（如 Ollama），雲端用 OpenAI 官方端點。"""
    global _client
    if _client is None:
        if config.LLM_PROVIDER == "local":
            # 本地端：base_url 指向 OpenAI 相容伺服器；金鑰不驗證但 SDK 要求非空。
            _client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
        else:
            _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


class Answer(BaseModel):
    """模型回傳的結構化結果。"""

    can_answer: bool = Field(description="知識庫內容是否足以回答此問題")
    answer: str = Field(description="給病人／家屬的回答；若無法回答，說明會轉介個管師")
    sources_used: List[int] = Field(
        default_factory=list,
        description="實際引用到的來源編號，對應提示中的 [1][2]... ",
    )


SYSTEM_PROMPT = """你是醫院個案管理系統中的「衛教問答助理」。
你的任務是根據提供的「衛教知識庫內容」，回答病人或家屬的疾病照護問題。

嚴格規則：
1. 只能依據「知識庫內容」回答，不可自行編造，也不可使用知識庫以外的醫療知識。
2. 若知識庫內容不足以回答，或問題超出衛教範圍（例如要求診斷、判讀檢驗、調整藥物劑量、
   處理緊急狀況），請把 can_answer 設為 false，並在 answer 中用親切的語氣說明
   「這部分我會幫您轉給個案管理師進一步協助」。
3. 回答一律使用繁體中文，語氣親切、白話、易懂，適合一般病人與家屬閱讀。
4. 在 sources_used 中列出你實際引用到的來源編號（例如 [1]、[3]）。
5. 絕不提供緊急醫療處置建議；遇到危急症狀，一律建議立即就醫或聯繫個案管理師。"""

# 本地模型沒有 OpenAI 那種「保證符合 schema」的強制結構化輸出，
# 因此把要求的 JSON 格式明白寫進提示，並要求「只輸出 JSON」。
# 另外針對 8B 級模型較弱的「轉介判斷」，用明確規則＋範例再強調一次。
_JSON_FORMAT_INSTRUCTION = """

請「只輸出一個 JSON 物件」，前後不要有任何說明文字或 markdown 標記，也不要在 JSON 後面
補上任何空白或重複字元。格式如下：
{
  "can_answer": true 或 false,
  "answer": "給病人／家屬的回答文字（繁體中文，簡潔，不要超過 300 字）",
  "sources_used": [1, 2]
}
其中 sources_used 是你實際引用到的來源編號陣列，若無則給空陣列 []。

can_answer 的判斷特別重要：
- 只要問題涉及「診斷、判讀檢驗數值、調整藥物或胰島素劑量、研判是否為某種疾病、
  緊急處置」，就一律把 can_answer 設為 false（這些必須轉給真人個案管理師），
  即使你想給一般性建議也一樣要設 false。
- 只有當知識庫內容足以「直接回答一般衛教問題」時，can_answer 才設 true。
範例：
  問「我的胰島素劑量該調成多少」→ {"can_answer": false, "answer": "...我會幫您轉給個案管理師...", "sources_used": []}
  問「糖尿病飲食要注意什麼」→ {"can_answer": true, "answer": "...", "sources_used": [1]}"""

# 解析失敗時的安全預設：一律轉介，絕不亂答。
_FALLBACK_ANSWER = Answer(
    can_answer=False,
    answer="抱歉，我這邊在處理您的問題時遇到一點狀況，我會將您的問題轉給個案管理師協助處理。",
    sources_used=[],
)


def answer_question(question: str, hits: List[dict]) -> Answer:
    """依檢索結果產生回答。沒有任何檢索結果時直接判定為需轉介。"""
    if not hits:
        return Answer(
            can_answer=False,
            answer="目前知識庫沒有找到相關的衛教資料，我會將您的問題轉給個案管理師協助處理。",
            sources_used=[],
        )

    context = "\n\n".join(
        f"[{i}] 來源：{h['title']}\n{h['text']}" for i, h in enumerate(hits, start=1)
    )
    user_prompt = (
        f"知識庫內容：\n{context}\n\n"
        f"病人／家屬的問題：\n{question}\n\n"
        "請根據以上知識庫內容作答。"
    )

    client = get_client()
    if config.LLM_PROVIDER == "local":
        return _answer_local(client, user_prompt)
    return _answer_openai(client, user_prompt)


def _answer_openai(client: OpenAI, user_prompt: str) -> Answer:
    """雲端 OpenAI：用原生 Structured Outputs，保證回傳符合 Answer schema。"""
    completion = client.beta.chat.completions.parse(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=Answer,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=2000,
    )
    return completion.choices[0].message.parsed


def _answer_local(client: OpenAI, user_prompt: str) -> Answer:
    """本地端：要求 JSON 模式輸出，再容錯解析成 Answer。解析失敗一律安全轉介。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + _JSON_FORMAT_INSTRUCTION},
        {"role": "user", "content": user_prompt},
    ]
    kwargs = dict(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=2000,
        # 抑制小模型「答完後退化成重複字元」的問題（曾見過整串 \t 撐爆長度上限、
        # 導致 JSON 被截斷）。penalty 讓它答完就收尾。
        frequency_penalty=0.6,
        presence_penalty=0.3,
    )
    try:
        # 優先用 JSON 模式（多數本地伺服器支援）；不支援就退回一般生成。
        try:
            completion = client.chat.completions.create(
                response_format={"type": "json_object"}, **kwargs
            )
        except Exception:
            completion = client.chat.completions.create(**kwargs)
        raw = completion.choices[0].message.content or ""
    except Exception:
        # 連線／伺服器層級的錯誤：安全轉介，不讓整支 API 掛掉。
        return _FALLBACK_ANSWER

    return _parse_answer(raw)


def _parse_answer(raw: str) -> Answer:
    """從模型輸出中容錯地抽出 JSON 並轉成 Answer；失敗則回傳安全轉介預設。"""
    text = (raw or "").strip()
    if not text:
        return _FALLBACK_ANSWER

    # 去掉 ```json ... ``` 之類的 markdown 圍欄
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()

    # 只取第一個 { 到最後一個 } 之間的內容（濾掉前後雜訊）
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    try:
        data = json.loads(text)
        return Answer.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError):
        # 小模型有時答案本身正確，但結尾多了雜訊／少了收尾的 } 而無法整段解析。
        # 這裡用正則從殘缺 JSON 中搶救 can_answer / answer / sources_used，
        # 救得回來就別浪費一個好答案；真的救不回來才安全轉介。
        return _salvage_answer(text)


def _salvage_answer(text: str) -> Answer:
    """從截斷或帶雜訊的 JSON 片段中盡量還原成 Answer；失敗則回傳安全轉介預設。"""
    m_can = re.search(r'"can_answer"\s*:\s*(true|false)', text, re.IGNORECASE)
    # 抓 "answer": "……"，允許字串未收尾（截斷）。
    m_ans = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)', text)
    if not (m_can and m_ans):
        return _FALLBACK_ANSWER

    can_answer = m_can.group(1).lower() == "true"
    try:
        # 把抓到的內容當成 JSON 字串內容還原跳脫字元（\n、\" 等）。
        answer = json.loads('"' + m_ans.group(1) + '"')
    except json.JSONDecodeError:
        answer = m_ans.group(1)
    answer = answer.strip()
    if not answer:
        return _FALLBACK_ANSWER

    m_src = re.search(r'"sources_used"\s*:\s*\[([\d,\s]*)\]', text)
    sources = [int(n) for n in re.findall(r"\d+", m_src.group(1))] if m_src else []

    return Answer(can_answer=can_answer, answer=answer, sources_used=sources)
