"""設定的讀寫。設定檔跟資料一樣放在 GitHub，本機不留副本。"""
import json
from datetime import date

CONFIG_PATH = "data/config.json"

DEFAULT_CONFIG = {
    # 記錄類別，使用者可自行增修，不需改程式
    "categories": ["Progress", "Blocker", "Market Intel", "To-do"],
    # 第一期的結束日（建議選一個週五），之後每 14 天推算一期
    "anchor_date": "2026-08-14",
    # 主管 email 為選填。留空時 Cloudflare Access 白名單只有使用者本人，系統照常可用。
    "manager_email": "",
    # 發布後的網址，發布流程填入，用於產生給主管的信件內容
    "site_url": "",
    # 彙整引擎，可切換 gemini／groq／anthropic，見 biweekly/summarize.py
    "summarize_provider": "gemini",
}


def load_config(store) -> dict:
    """讀設定。檔案不存在時回傳預設值，缺少的欄位也由預設值補齊。"""
    try:
        raw = store.read_file(CONFIG_PATH)
    except FileNotFoundError:
        return dict(DEFAULT_CONFIG)

    merged = dict(DEFAULT_CONFIG)
    merged.update(json.loads(raw.decode("utf-8")))
    return merged


def save_config(store, data: dict) -> None:
    """寫回設定。"""
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    store.commit_files({CONFIG_PATH: body}, "chore(biweekly): 更新設定")


def anchor_date(data: dict) -> date:
    """把設定中的錨定日字串轉成 date。"""
    return date.fromisoformat(data["anchor_date"])
