"""記錄的資料模型與 Markdown 序列化。

一筆記錄存成一個 .md 檔，開頭是 YAML frontmatter，後面是本文。
用純文字的好處是在 GitHub 網頁上就能直接讀、能全文搜尋、有版本歷史。
"""
import os
from dataclasses import dataclass, field
from datetime import datetime

import yaml

ENTRIES_ROOT = "data/entries"
ATTACHMENTS_ROOT = "data/attachments"


@dataclass
class Entry:
    timestamp: datetime
    category: str
    body: str
    source: str = "自己"
    include_in_report: bool = True
    attachments: list[str] = field(default_factory=list)


def to_markdown(entry: Entry) -> str:
    """把一筆記錄轉成含 frontmatter 的 Markdown 文字。"""
    meta = {
        "timestamp": entry.timestamp.isoformat(),
        "category": entry.category,
        "source": entry.source,
        "include_in_report": entry.include_in_report,
        "attachments": list(entry.attachments),
    }
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    return f"---\n{front}---\n\n{entry.body.strip()}\n"


def from_markdown(text: str) -> Entry:
    """把 Markdown 文字讀回一筆記錄。格式不對就明確報錯，不猜。"""
    if not text.startswith("---\n"):
        raise ValueError("記錄檔缺少 frontmatter，無法解析")
    try:
        _, front, body = text.split("---\n", 2)
    except ValueError as exc:
        raise ValueError("記錄檔的 frontmatter 沒有正確結束") from exc

    meta = yaml.safe_load(front) or {}
    return Entry(
        timestamp=datetime.fromisoformat(str(meta["timestamp"])),
        category=meta["category"],
        body=body.strip(),
        source=meta.get("source") or "自己",
        include_in_report=meta.get("include_in_report", True),
        attachments=list(meta.get("attachments") or []),
    )


def _stamp(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%dT%H%M%S")


def _month(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m")


def _safe_segment(name: str) -> str:
    """把路徑分隔符清掉，只取最後一段，避免路徑穿越。"""
    return os.path.basename(name.replace("\\", "/"))


def entry_path(entry: Entry) -> str:
    """記錄在 repo 中的路徑，依月份分資料夾。"""
    safe_category = _safe_segment(entry.category)
    return f"{ENTRIES_ROOT}/{_month(entry.timestamp)}/{_stamp(entry.timestamp)}_{safe_category}.md"


def attachment_path(timestamp: datetime, filename: str) -> str:
    """附件在 repo 中的路徑。檔名只取最後一段，避免路徑穿越。"""
    safe_name = _safe_segment(filename)
    return f"{ATTACHMENTS_ROOT}/{_month(timestamp)}/{_stamp(timestamp)}_{safe_name}"


def all_paths(entry: Entry) -> list[str]:
    """一筆記錄佔用的全部檔案：記錄本身，加上它的所有附件。

    刪除記錄時要用這個，不能只刪 .md —— 否則附件會變成沒有任何記錄指向的
    孤兒檔案，永遠留在 repo 裡，既認不出是誰的也不敢刪。
    """
    return [entry_path(entry), *entry.attachments]
