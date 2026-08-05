import json
from datetime import date
from unittest.mock import Mock

from biweekly import config


def test_設定檔不存在時回傳預設值():
    store = Mock()
    store.read_file.side_effect = FileNotFoundError
    data = config.load_config(store)
    assert data["categories"] == ["Progress", "Blocker", "Market Intel", "To-do"]
    assert data["manager_email"] == ""


def test_既有設定會覆蓋預設值():
    store = Mock()
    store.read_file.return_value = json.dumps(
        {"categories": ["自訂類別"]}, ensure_ascii=False
    ).encode()
    data = config.load_config(store)
    assert data["categories"] == ["自訂類別"]


def test_既有設定缺少的欄位由預設值補齊():
    store = Mock()
    store.read_file.return_value = json.dumps({"categories": ["自訂類別"]}).encode()
    data = config.load_config(store)
    assert "anchor_date" in data
    assert data["manager_email"] == ""


def test_儲存設定時中文不被跳脫():
    store = Mock()
    config.save_config(store, {"categories": ["市場情報"]})
    written = store.commit_files.call_args.args[0][config.CONFIG_PATH]
    assert "市場情報" in written.decode("utf-8")


def test_錨定日轉成_date_物件():
    assert config.anchor_date({"anchor_date": "2026-08-14"}) == date(2026, 8, 14)


def test_主管_email_留空是合法的():
    store = Mock()
    store.read_file.return_value = json.dumps({"manager_email": ""}).encode()
    assert config.load_config(store)["manager_email"] == ""


def test_預設設定含彙整供應商():
    assert config.DEFAULT_CONFIG["summarize_provider"] == "gemini"
