from unittest.mock import Mock

from biweekly import notify
from biweekly.tests.conftest import FakeResponse


def test_有_token_時會呼叫_LINE_廣播_API(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_TOKEN", "測試用假token")
    post = Mock(return_value=FakeResponse({}))
    monkeypatch.setattr(notify.requests, "post", post)

    notify.notify_error("發布失敗")

    assert post.call_count == 1
    sent_text = post.call_args.kwargs["json"]["messages"][0]["text"]
    assert "發布失敗" in sent_text


def test_沒有_token_時不呼叫_API_但要印出訊息(monkeypatch, capsys):
    monkeypatch.delenv("LINE_CHANNEL_TOKEN", raising=False)
    post = Mock()
    monkeypatch.setattr(notify.requests, "post", post)

    notify.notify_error("發布失敗")

    assert post.call_count == 0
    assert "發布失敗" in capsys.readouterr().out


def test_通知本身失敗時不得往外拋例外(monkeypatch, capsys):
    monkeypatch.setenv("LINE_CHANNEL_TOKEN", "測試用假token")
    monkeypatch.setattr(
        notify.requests, "post", Mock(side_effect=RuntimeError("網路斷線"))
    )

    notify.notify_error("發布失敗")  # 不應拋出例外

    output = capsys.readouterr().out
    assert "網路斷線" in output
    assert "發布失敗" in output
