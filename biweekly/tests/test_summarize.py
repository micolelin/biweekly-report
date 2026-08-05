from datetime import date, datetime
from unittest.mock import Mock

import pytest

from biweekly import summarize
from biweekly.entries import Entry
from biweekly.periods import TAIPEI
from biweekly.tests.conftest import FakeResponse, FakeSession


def _entry(day, category, body, include=True):
    return Entry(
        timestamp=datetime(2026, 8, day, 10, 0, tzinfo=TAIPEI),
        category=category,
        body=body,
        include_in_report=include,
    )


def test_prompt_含所有納入的記錄():
    prompt = summarize.build_prompt(
        [_entry(4, "進度", "完成 TCO 試算"), _entry(5, "問題", "客戶延後決策")],
        date(2026, 8, 1),
        date(2026, 8, 14),
    )
    assert "完成 TCO 試算" in prompt
    assert "客戶延後決策" in prompt


def test_prompt_含期別起訖():
    prompt = summarize.build_prompt([], date(2026, 8, 1), date(2026, 8, 14))
    assert "2026-08-01" in prompt
    assert "2026-08-14" in prompt


def test_prompt_標示每筆記錄的類別與日期():
    prompt = summarize.build_prompt(
        [_entry(4, "市場情報", "競爭對手降價")], date(2026, 8, 1), date(2026, 8, 14)
    )
    assert "市場情報" in prompt
    assert "2026-08-04" in prompt


def test_系統提示明確禁止捏造內容():
    assert "must not" in summarize.SYSTEM_PROMPT
    assert "None this period" in summarize.SYSTEM_PROMPT


def test_系統提示要求四個固定段落():
    for section in ["Highlights", "Progress", "Blockers & Support Needed", "Next Period"]:
        assert section in summarize.SYSTEM_PROMPT


def test_收集記錄時會排除標記為不進報告的():
    store = Mock()
    store.list_dir.return_value = ["data/entries/2026-08/a.md"]
    store.read_file.return_value = (
        "---\n"
        "timestamp: '2026-08-04T10:00:00+08:00'\n"
        "category: 進度\n"
        "include_in_report: false\n"
        "---\n"
        "\n"
        "這筆不要進報告\n"
    ).encode()
    assert summarize.collect_period_entries(store, date(2026, 8, 1), date(2026, 8, 14)) == []


def test_收集記錄時會排除不在期間內的():
    store = Mock()
    store.list_dir.return_value = ["data/entries/2026-08/a.md"]
    store.read_file.return_value = (
        "---\n"
        "timestamp: '2026-08-20T10:00:00+08:00'\n"
        "category: 進度\n"
        "---\n"
        "\n"
        "這是下一期的\n"
    ).encode()
    assert summarize.collect_period_entries(store, date(2026, 8, 1), date(2026, 8, 14)) == []


def test_收集記錄依時間排序():
    store = Mock()
    store.list_dir.return_value = [
        "data/entries/2026-08/b.md",
        "data/entries/2026-08/a.md",
    ]

    def fake_read(path):
        day = "05" if path.endswith("b.md") else "04"
        return (
            f"---\ntimestamp: '2026-08-{day}T10:00:00+08:00'\n"
            f"category: 進度\n---\n\n第 {day} 天\n"
        ).encode()

    store.read_file.side_effect = fake_read
    items = summarize.collect_period_entries(store, date(2026, 8, 1), date(2026, 8, 14))
    assert [item.body for item in items] == ["第 04 天", "第 05 天"]


def test_期別跨月時兩個月的資料夾都會被讀到():
    store = Mock()

    def fake_list_dir(path):
        if path.endswith("2026-07"):
            return ["data/entries/2026-07/a.md"]
        if path.endswith("2026-08"):
            return ["data/entries/2026-08/b.md"]
        raise AssertionError(f"未預期的路徑：{path}")

    store.list_dir.side_effect = fake_list_dir

    def fake_read_file(path):
        if path.endswith("a.md"):
            return (
                "---\ntimestamp: '2026-07-30T10:00:00+08:00'\n"
                "category: 進度\n---\n\n七月的記錄\n"
            ).encode()
        if path.endswith("b.md"):
            return (
                "---\ntimestamp: '2026-08-05T10:00:00+08:00'\n"
                "category: 進度\n---\n\n八月的記錄\n"
            ).encode()
        raise AssertionError(f"未預期的路徑：{path}")

    store.read_file.side_effect = fake_read_file

    items = summarize.collect_period_entries(store, date(2026, 7, 28), date(2026, 8, 10))
    assert [item.body for item in items] == ["七月的記錄", "八月的記錄"]


def test_沒有任何記錄時不呼叫_API():
    client = Mock()
    text = summarize.summarize([], date(2026, 8, 1), date(2026, 8, 14), client=client)
    assert client.messages.create.call_count == 0
    assert "No notes recorded" in text


def test_呼叫_API_時帶上系統提示與模型():
    client = Mock()
    client.messages.create.return_value = Mock(
        content=[Mock(text="## Highlights\n- Finished the estimate")]
    )
    text = summarize.summarize(
        [_entry(4, "進度", "完成 TCO 試算")],
        date(2026, 8, 1),
        date(2026, 8, 14),
        provider="anthropic",
        client=client,
    )
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == summarize.PROVIDER_MODELS["anthropic"]
    assert kwargs["system"] == summarize.SYSTEM_PROMPT
    assert text == "## Highlights\n- Finished the estimate"


def test_預設供應商為_gemini():
    assert summarize.DEFAULT_PROVIDER == "gemini"


def test_三個供應商都有對應模型():
    assert summarize.PROVIDER_MODELS == {
        "gemini": "gemini-flash-latest",
        "groq": "llama-3.3-70b-versatile",
        "anthropic": "claude-opus-5",
    }


def test_gemini_送出的系統提示與內容正確(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "假gemini金鑰")
    session = FakeSession(
        {
            (
                "POST",
                "generateContent?key=假gemini金鑰",
            ): FakeResponse(
                {"candidates": [{"content": {"parts": [{"text": "整理好的草稿"}]}}]}
            )
        }
    )
    items = [_entry(4, "進度", "完成 TCO 試算")]
    start, end = date(2026, 8, 1), date(2026, 8, 14)
    summarize.summarize(items, start, end, provider="gemini", session=session)

    body = session.json_bodies("POST", "generateContent?key=假gemini金鑰")[0]
    assert body["systemInstruction"]["parts"][0]["text"] == summarize.SYSTEM_PROMPT
    assert body["contents"][0]["parts"][0]["text"] == summarize.build_prompt(
        items, start, end
    )


def test_groq_送出的系統提示與內容正確(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "假groq金鑰")
    session = FakeSession(
        {
            ("POST", "chat/completions"): FakeResponse(
                {"choices": [{"message": {"content": "整理好的草稿"}}]}
            )
        }
    )
    items = [_entry(4, "進度", "完成 TCO 試算")]
    start, end = date(2026, 8, 1), date(2026, 8, 14)
    summarize.summarize(items, start, end, provider="groq", session=session)

    body = session.json_bodies("POST", "chat/completions")[0]
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == summarize.SYSTEM_PROMPT
    assert body["messages"][1]["content"] == summarize.build_prompt(items, start, end)


def test_gemini_回傳文字被正確取出(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "假gemini金鑰")
    session = FakeSession(
        {
            (
                "POST",
                "generateContent?key=假gemini金鑰",
            ): FakeResponse(
                {"candidates": [{"content": {"parts": [{"text": "整理好的草稿"}]}}]}
            )
        }
    )
    text = summarize.summarize(
        [_entry(4, "進度", "完成 TCO 試算")],
        date(2026, 8, 1),
        date(2026, 8, 14),
        provider="gemini",
        session=session,
    )
    assert text == "整理好的草稿"


def test_groq_回傳文字被正確取出(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "假groq金鑰")
    session = FakeSession(
        {
            ("POST", "chat/completions"): FakeResponse(
                {"choices": [{"message": {"content": "整理好的草稿"}}]}
            )
        }
    )
    text = summarize.summarize(
        [_entry(4, "進度", "完成 TCO 試算")],
        date(2026, 8, 1),
        date(2026, 8, 14),
        provider="groq",
        session=session,
    )
    assert text == "整理好的草稿"


def test_未知供應商要拋_ValueError():
    with pytest.raises(ValueError) as excinfo:
        summarize.summarize(
            [_entry(4, "進度", "完成 TCO 試算")],
            date(2026, 8, 1),
            date(2026, 8, 14),
            provider="不存在的供應商",
        )
    message = str(excinfo.value)
    for name in ("gemini", "groq", "anthropic"):
        assert name in message


def test_缺少金鑰時錯誤訊息要指名環境變數(monkeypatch):
    items = [_entry(4, "進度", "完成 TCO 試算")]
    start, end = date(2026, 8, 1), date(2026, 8, 14)

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        summarize.summarize(
            items, start, end, provider="gemini", session=FakeSession()
        )

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        summarize.summarize(items, start, end, provider="groq", session=FakeSession())

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        summarize.summarize(items, start, end, provider="anthropic")


def test_HTTP_錯誤要拋出且訊息指名供應商(monkeypatch):
    items = [_entry(4, "進度", "完成 TCO 試算")]
    start, end = date(2026, 8, 1), date(2026, 8, 14)

    monkeypatch.setenv("GEMINI_API_KEY", "假gemini金鑰")
    gemini_session = FakeSession(
        {
            ("POST", "generateContent?key=假gemini金鑰"): FakeResponse(
                {"error": "壞掉了"}, status_code=500
            )
        }
    )
    with pytest.raises(RuntimeError, match="gemini"):
        summarize.summarize(
            items, start, end, provider="gemini", session=gemini_session
        )

    monkeypatch.setenv("GROQ_API_KEY", "假groq金鑰")
    groq_session = FakeSession(
        {
            ("POST", "chat/completions"): FakeResponse(
                {"error": "壞掉了"}, status_code=500
            )
        }
    )
    with pytest.raises(RuntimeError, match="groq"):
        summarize.summarize(items, start, end, provider="groq", session=groq_session)


def test_沒有記錄時三個供應商都不會呼叫_API():
    start, end = date(2026, 8, 1), date(2026, 8, 14)
    for provider in summarize.PROVIDER_MODELS:
        session = FakeSession()
        client = Mock()
        text = summarize.summarize(
            [], start, end, provider=provider, session=session, client=client
        )
        assert session.calls == []
        assert client.messages.create.call_count == 0
        assert "No notes recorded" in text
