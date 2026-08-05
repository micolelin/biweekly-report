"""期別計算：一期兩週，由設定檔中的錨定日往後推算。"""
from datetime import date, datetime, timedelta, timezone

PERIOD_DAYS = 14
TAIPEI = timezone(timedelta(hours=8))


def taipei_today() -> date:
    """取得台北時間的今天。"""
    return datetime.now(TAIPEI).date()


def period_end(anchor: date, today: date) -> date:
    """回傳 today 所屬期別的結束日（含當天）。

    錨定日是第一期的結束日。今天若早於或等於錨定日，仍屬第一期。
    """
    if today <= anchor:
        return anchor
    elapsed = (today - anchor).days
    steps = -(-elapsed // PERIOD_DAYS)  # 無條件進位
    return anchor + timedelta(days=steps * PERIOD_DAYS)


def period_range(anchor: date, today: date) -> tuple[date, date]:
    """回傳 today 所屬期別的 (起始日, 結束日)，兩端都含。"""
    end = period_end(anchor, today)
    return end - timedelta(days=PERIOD_DAYS - 1), end


def period_label(end: date) -> str:
    """期別標籤，用結束日的 ISO 格式，例如 2026-08-14。"""
    return end.isoformat()
