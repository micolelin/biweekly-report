from datetime import datetime

import pytest

from biweekly import entries
from biweekly.periods import TAIPEI


def _sample_entry():
    return entries.Entry(
        timestamp=datetime(2026, 8, 4, 15, 30, tzinfo=TAIPEI),
        category="進度",
        body="完成 TCO 試算表，寄給客戶確認。",
        source="自己",
        include_in_report=True,
        attachments=["data/attachments/2026-08/tco.pptx"],
    )


def test_序列化後再讀回來_內容完全一致():
    original = _sample_entry()
    restored = entries.from_markdown(entries.to_markdown(original))
    assert restored == original


def test_序列化結果含_frontmatter_與本文():
    text = entries.to_markdown(_sample_entry())
    assert text.startswith("---\n")
    assert "category: 進度" in text
    assert "完成 TCO 試算表" in text


def test_中文不會被轉成_unicode_跳脫碼():
    text = entries.to_markdown(_sample_entry())
    assert "\\u" not in text


def test_時間戳記保留台北時區():
    restored = entries.from_markdown(entries.to_markdown(_sample_entry()))
    assert restored.timestamp.utcoffset().total_seconds() == 8 * 3600


def test_缺少選填欄位時套用預設值():
    text = (
        "---\n"
        "timestamp: '2026-08-04T15:30:00+08:00'\n"
        "category: 待辦\n"
        "---\n"
        "\n"
        "記得追進度\n"
    )
    entry = entries.from_markdown(text)
    assert entry.source == "自己"
    assert entry.include_in_report is True
    assert entry.attachments == []
    assert entry.body == "記得追進度"


def test_沒有_frontmatter_要明確報錯():
    with pytest.raises(ValueError, match="frontmatter"):
        entries.from_markdown("這只是一段純文字")


def test_記錄路徑依月份分資料夾且含類別():
    path = entries.entry_path(_sample_entry())
    assert path == "data/entries/2026-08/2026-08-04T153000_進度.md"


def test_附件路徑依月份分資料夾():
    path = entries.attachment_path(
        datetime(2026, 8, 4, 15, 30, tzinfo=TAIPEI), "報價單.xlsx"
    )
    assert path == "data/attachments/2026-08/2026-08-04T153000_報價單.xlsx"


def test_附件檔名中的路徑分隔符要被清掉():
    path = entries.attachment_path(
        datetime(2026, 8, 4, 15, 30, tzinfo=TAIPEI), "../../壞檔名.txt"
    )
    assert path == "data/attachments/2026-08/2026-08-04T153000_壞檔名.txt"


def test_記錄類別中的路徑分隔符要被清掉():
    entry = entries.Entry(
        timestamp=datetime(2026, 8, 4, 15, 30, tzinfo=TAIPEI),
        category="../../壞類別",
        body="測試路徑穿越",
    )
    path = entries.entry_path(entry)
    assert path == "data/entries/2026-08/2026-08-04T153000_壞類別.md"


def test_一筆記錄的所有檔案含本身與附件():
    entry = _sample_entry()
    paths = entries.all_paths(entry)
    assert entries.entry_path(entry) in paths
    assert "data/attachments/2026-08/tco.pptx" in paths
    assert len(paths) == 2


def test_沒有附件時只回傳記錄本身():
    entry = _sample_entry()
    entry.attachments = []
    assert entries.all_paths(entry) == [entries.entry_path(entry)]


def test_記錄本身排在附件之前():
    entry = _sample_entry()
    assert entries.all_paths(entry)[0] == entries.entry_path(entry)
