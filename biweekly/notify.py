"""失敗通知：把錯誤推到 LINE，讓排程或發布的失敗不會被忽略。"""
import os

import requests

BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"


def notify_error(message: str) -> None:
    """推播錯誤訊息到 LINE。

    這個函式本身絕不拋出例外 —— 它是錯誤處理的最後一道，
    如果連它都會炸，就會蓋掉原本真正的錯誤。
    """
    token = os.environ.get("LINE_CHANNEL_TOKEN")
    if not token:
        print(f"[notify] 未設定 LINE_CHANNEL_TOKEN，無法推播。原訊息：{message}")
        return

    try:
        response = requests.post(
            BROADCAST_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "messages": [
                    {"type": "text", "text": f"⚠️ 雙週報告系統錯誤\n{message}"}
                ]
            },
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - 這裡刻意攔下所有例外
        print(f"[notify] 推播失敗：{exc}。原訊息：{message}")
