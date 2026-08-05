"""用 Claude 把兩週的零散記錄整理成報告草稿。

核心約束：Claude 只做整理、歸納、摘要，不做內容生成。
報告是給主管看的，只要有一句是編出來的，信任就沒了。
"""
import os
from datetime import date

import requests

from . import entries as entries_mod

DEFAULT_PROVIDER = "gemini"

PROVIDER_MODELS = {
    "gemini": "gemini-flash-latest",
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-opus-5",
}

MODEL = PROVIDER_MODELS[DEFAULT_PROVIDER]
MAX_TOKENS = 4000

ENV_HINT = "請確認 /Users/admin/Documents/m-agent/.env 已設定並載入。"

EMPTY_SECTION = "None this period"

SYSTEM_PROMPT = """You organise biweekly work reports.

You will receive a set of raw work notes covering one reporting period. Your
job is to organise them into a structured draft report.

The notes may be written in Chinese, English, or a mix. **Your output must be
entirely in English**, regardless of the language of the notes.

Use exactly these four sections, as Markdown level-2 headings:

## Highlights
(At most 3 bullets, one sentence each. Pick what the manager most needs to know.)

## Progress
(Group by topic. Do not produce a chronological log.)

## Blockers & Support Needed
(State plainly what is stuck, and what decision or resource is needed from the
manager.)

## Next Period

Strict rules:

1. You **must not** add any information that is not present in the raw notes.
   Do not speculate, do not supply background, do not embellish results.
2. Every sentence must be traceable to a specific raw note.
3. If a section has no supporting material, write exactly "None this period".
   **Do not** invent content to fill it.
4. Preserve concrete figures, company names and product names exactly as they
   appear in the notes. Do not soften them into vague phrasing.
5. Translate faithfully. When a note is in Chinese, render its meaning in
   English without adding interpretation. Keep proper nouns and product codes
   in their original form.
"""


def collect_period_entries(store, start: date, end: date) -> list[entries_mod.Entry]:
    """抓取期間內、且標記為要進報告的記錄，依時間排序。

    期別可能跨月，所以起訖兩個月的資料夾都要看。
    """
    months = {start.strftime("%Y-%m"), end.strftime("%Y-%m")}
    paths = []
    for month in sorted(months):
        paths.extend(store.list_dir(f"{entries_mod.ENTRIES_ROOT}/{month}"))

    collected = []
    for path in paths:
        entry = entries_mod.from_markdown(store.read_file(path).decode("utf-8"))
        if not entry.include_in_report:
            continue
        if not start <= entry.timestamp.date() <= end:
            continue
        collected.append(entry)

    collected.sort(key=lambda item: item.timestamp)
    return collected


def build_prompt(items: list[entries_mod.Entry], start: date, end: date) -> str:
    """把記錄組成送給 Claude 的訊息。這是純函式，方便完整測試。"""
    lines = [
        f"Reporting period: {start.isoformat()} to {end.isoformat()}",
        "",
        f"Raw work notes for this period ({len(items)} in total):",
        "",
    ]
    for item in items:
        lines.append(
            f"- [{item.timestamp.strftime('%Y-%m-%d')}]"
            f"[{item.category}][source: {item.source}] {item.body}"
        )
    return "\n".join(lines)


def _require_env(name: str) -> str:
    """讀取必要的環境變數，缺少時明確指名是哪一個、去哪裡設定。"""
    api_key = os.environ.get(name)
    if not api_key:
        raise RuntimeError(f"找不到 {name}。{ENV_HINT}")
    return api_key


def _raise_provider_failure(provider: str, exc: Exception):
    """統一把底層錯誤包成「指名供應商、提示可切換」的錯誤，不吞掉原始錯誤。"""
    raise RuntimeError(
        f"呼叫 {provider} 彙整失敗，可在工作台「產生報告」分頁切換其他彙整引擎再試一次。"
        f"詳細錯誤：{exc}"
    ) from exc


def _call_gemini(prompt: str, session=None) -> str:
    """送出 prompt 給 Gemini，取回文字。"""
    api_key = _require_env("GEMINI_API_KEY")
    session = session or requests
    model = PROVIDER_MODELS["gemini"]
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
    }
    try:
        response = session.post(url, json=body)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:  # noqa: BLE001
        _raise_provider_failure("gemini", exc)


def _call_groq(prompt: str, session=None) -> str:
    """送出 prompt 給 Groq，取回文字。"""
    api_key = _require_env("GROQ_API_KEY")
    session = session or requests
    model = PROVIDER_MODELS["groq"]
    url = "https://api.groq.com/openai/v1/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": MAX_TOKENS,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = session.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        _raise_provider_failure("groq", exc)


def _call_anthropic(prompt: str, client=None) -> str:
    """送出 prompt 給 Anthropic，取回文字。"""
    if client is None:
        import anthropic

        api_key = _require_env("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=PROVIDER_MODELS["anthropic"],
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as exc:  # noqa: BLE001
        _raise_provider_failure("anthropic", exc)


def summarize(
    items: list[entries_mod.Entry],
    start: date,
    end: date,
    provider: str | None = None,
    session=None,
    client=None,
) -> str:
    """產生報告草稿。沒有記錄時直接回傳固定文字，不浪費 API 呼叫。

    provider 決定用哪個服務彙整，三者收到完全相同的 SYSTEM_PROMPT。
    不做自動 fallback：某個供應商失敗就是失敗，讓使用者自己決定要不要切換。
    """
    if not items:
        return (
            f"## Highlights\n\nNo notes recorded for "
            f"{start.isoformat()} – {end.isoformat()}.\n\n"
            f"## Progress\n\n{EMPTY_SECTION}\n\n"
            f"## Blockers & Support Needed\n\n{EMPTY_SECTION}\n\n"
            f"## Next Period\n\n{EMPTY_SECTION}\n"
        )

    provider = provider or DEFAULT_PROVIDER
    if provider not in PROVIDER_MODELS:
        available = "、".join(PROVIDER_MODELS.keys())
        raise ValueError(f"不支援的彙整供應商：{provider}。可用供應商：{available}")

    prompt = build_prompt(items, start, end)

    if provider == "gemini":
        return _call_gemini(prompt, session=session)
    if provider == "groq":
        return _call_groq(prompt, session=session)
    return _call_anthropic(prompt, client=client)
