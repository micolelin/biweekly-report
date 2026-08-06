"""整合測試打的是已部署的 Worker，不是本機程式。

沒有設定帳密時整個目錄會被 skip，這樣預設的 `pytest` 仍然完全離線。

注意：所有測試共用同一個 `slot=test` 資料檔（見下面的 `_cleanup_test_slot` 與
`poll`），不要同時跑兩份這個套件——兩個 run 會互相覆蓋對方寫入的狀態，跑出來的
失敗會長得像 API 或邏輯壞了，其實只是撞在一起。開發時曾因此白花時間排查。
"""
import os
import time

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


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_slot(auth, base_url):
    """整個 session 結束後把 test slot 清乾淨。

    各測試只在自己開始時做一次 DELETE，不代表測試結束時是乾淨的——最後一個
    使用 test slot 的測試通常會留一筆寫入，於是 data 分支上就留了一個殘留
    commit。這裡用 session 範圍、autouse 的 fixture，在整個檔案的所有測試
    都跑完後才做最後一次 DELETE，不依賴任何單一測試自己收尾。

    刻意不透過 `api` fixture：`api` 是 function scope，session scope 的
    fixture 沒辦法依賴它，所以這裡直接用 `auth`／`base_url`（兩者都是
    session scope）自己組一次請求。
    """
    yield
    requests.request(
        "DELETE", f"{base_url}/api/table?slot=test", auth=auth, timeout=30
    )


@pytest.fixture
def poll(api):
    """回傳一個會重試的 api() 版本，用來讀「剛寫入／剛刪除」之後的狀態。

    GitHub 的 Contents API 不是 read-after-write 一致：DELETE 或 PUT 剛成功，
    緊接著的 GET 有機會還讀到舊版本（實測差距約在 1 秒內）。這不是 Worker
    的錯，Worker 本身沒有狀態、每次都是即時轉發到 GitHub。重試由測試自己
    負責，不要求 Worker 加重試——正式頁面不會有「剛刪除、剛寫入就馬上重讀」
    這種用法，加了只會拖慢真實流量，卻不保證真的關掉這個時間差。

    用法：`poll("GET", "/api/table?slot=test", lambda r: r.json()["sha"] is None)`，
    最多重試到 2 秒，每次間隔 100～200ms，逾時就回傳最後一次的結果（讓斷言
    用真實內容失敗，而不是吞掉逾時假裝成功）。
    """

    def call(method, path, predicate, timeout=2.0, interval=0.15, **kwargs):
        deadline = time.monotonic() + timeout
        response = api(method, path, **kwargs)
        while not predicate(response) and time.monotonic() < deadline:
            time.sleep(interval)
            response = api(method, path, **kwargs)
        return response

    return call
