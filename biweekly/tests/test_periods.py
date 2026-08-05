from datetime import date

from biweekly import periods


def test_今天正好是錨定日時_本期就結束在錨定日():
    anchor = date(2026, 8, 14)
    assert periods.period_end(anchor, date(2026, 8, 14)) == date(2026, 8, 14)


def test_今天早於錨定日時_仍屬於第一期():
    anchor = date(2026, 8, 14)
    assert periods.period_end(anchor, date(2026, 8, 4)) == date(2026, 8, 14)


def test_錨定日隔天就進入下一期():
    anchor = date(2026, 8, 14)
    assert periods.period_end(anchor, date(2026, 8, 15)) == date(2026, 8, 28)


def test_正好滿十四天時_不會多推一期():
    anchor = date(2026, 8, 14)
    assert periods.period_end(anchor, date(2026, 8, 28)) == date(2026, 8, 28)


def test_跨越多期後仍算得出正確期別():
    anchor = date(2026, 8, 14)
    assert periods.period_end(anchor, date(2026, 12, 1)) == date(2026, 12, 4)


def test_期間為十四天_起始日為結束日往前十三天():
    anchor = date(2026, 8, 14)
    start, end = periods.period_range(anchor, date(2026, 8, 4))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 14)
    assert (end - start).days == periods.PERIOD_DAYS - 1


def test_期別標籤用結束日的_ISO_格式():
    assert periods.period_label(date(2026, 8, 14)) == "2026-08-14"
