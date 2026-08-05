"""把 Streamlit Cloud 的 secrets 灌進環境變數。

本機執行時憑證來自 .env（已經在環境變數裡），這個函式不會覆蓋它們；
部署到 Streamlit Cloud 時沒有 .env，改由 st.secrets 提供。
兩種情境共用同一份程式碼，其餘模組一律只讀 os.environ，不需要判斷自己跑在哪裡。

這是 biweekly/ 底下唯一可以 import streamlit 的模組。
"""
import os

SECRET_KEYS = (
    "GITHUB_TOKEN",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "ANTHROPIC_API_KEY",
)


def load_secrets_into_env() -> None:
    """把 st.secrets 中的憑證複製到環境變數。

    已存在於 os.environ 的鍵不會被覆蓋 —— 本機的 .env 優先。
    本機沒有 secrets 檔案時 st.secrets 會拋例外，這裡攔下並說明，
    讓工作台仍然起得來（本機本來就不需要它）。
    """
    try:
        import streamlit as st

        secrets = st.secrets
    except Exception as exc:  # noqa: BLE001 - 本機無 secrets 檔是正常狀況
        print(f"[secrets] 讀不到 Streamlit secrets（{exc}）。改用環境變數，本機執行時屬正常。")
        return

    loaded = []
    for key in SECRET_KEYS:
        if os.environ.get(key):
            continue
        try:
            value = secrets[key]
        except Exception:  # noqa: BLE001 - 該鍵未設定，跳過即可
            continue
        if value:
            os.environ[key] = str(value)
            loaded.append(key)

    if loaded:
        print(f"[secrets] 已從 Streamlit secrets 載入：{'、'.join(loaded)}")
