"""整合測試打的是已部署的 Worker，不是本機程式。

沒有設定帳密時整個目錄會被 skip，這樣預設的 `pytest` 仍然完全離線。
"""
import os

import pytest
import requests

BASE_URL = os.environ.get(
    "TABLE_BASE_URL", "https://biweekly-report.micole-m-lin.workers.dev"
)


@pytest.fixture(scope="session")
def auth():
    user = os.environ.get("REPORT_USER")
    password = os.environ.get("REPORT_PASSWORD")
    if not (user and password):
        pytest.skip("未設定 REPORT_USER / REPORT_PASSWORD，跳過整合測試")
    return (user, password)


@pytest.fixture(scope="session")
def base_url(auth):
    """刻意依賴 auth：沒設帳密時連不帶密碼的測試也一起 skip，
    這樣預設的 `pytest` 一個網路請求都不會發出去。"""
    return BASE_URL.rstrip("/")


@pytest.fixture
def api(auth, base_url):
    """回傳一個打 API 的函式，自動帶上帳密。"""

    def call(method, path, **kwargs):
        return requests.request(
            method, f"{base_url}{path}", auth=auth, timeout=30, **kwargs
        )

    return call
