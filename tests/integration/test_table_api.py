"""對已部署的 Worker 做端對端驗證。

寫入類的測試一律使用 ?slot=test，不會碰到正式資料。
"""
import requests


def test_未帶帳密時_api_一律回_401(base_url):
    """API 不能成為繞過密碼保護的後門。"""
    response = requests.get(f"{base_url}/api/version", timeout=30)
    assert response.status_code == 401


def test_帶帳密時_version_回傳整數版本號(api):
    response = api("GET", "/api/version")
    assert response.status_code == 200
    assert isinstance(response.json()["version"], int)


def test_未知的_api_路徑回_404(api):
    response = api("GET", "/api/不存在的端點")
    assert response.status_code == 404


def test_取得表格時回傳資料與_sha(api):
    response = api("GET", "/api/table?slot=test")
    assert response.status_code == 200

    body = response.json()
    assert body["data"]["v"] == 1
    assert isinstance(body["data"]["rows"], list)
    assert "sha" in body


def test_測試槽的檔案不存在時回空表而非錯誤(api, poll):
    """第一次使用時沒有資料檔，這是正常狀況不是錯誤。

    DELETE 剛成功，緊接著的 GET 有機會在 GitHub Contents API 的
    read-after-write 空窗期內還讀到舊版本，所以用 poll 等 sha 真的變成
    None 再斷言（見 conftest.py 的 poll fixture 說明）。
    """
    api("DELETE", "/api/table?slot=test")

    response = poll("GET", "/api/table?slot=test", lambda r: r.json()["sha"] is None)
    assert response.status_code == 200
    assert response.json()["data"]["rows"] == []
    assert response.json()["sha"] is None


def test_不合法的_slot_被拒絕(api):
    """slot 直接對應檔名，不擋就等於讓外部指定要讀哪個檔。"""
    response = api("GET", "/api/table?slot=../../etc/passwd")
    assert response.status_code == 400


def test_繼承自_object_prototype_的_slot_名稱也要被拒絕(api):
    """物件字面量的 [] 存取會沿原型鏈往上找，slot=constructor 這類名稱
    會拿到 Object.prototype 上的東西而不是 undefined，等於白名單被繞過。"""
    for slot in ("constructor", "toString"):
        response = api("GET", f"/api/table?slot={slot}")
        assert response.status_code == 400, f"slot={slot} 應該被拒絕"


def test_寫入後讀得回同樣的內容(api, poll):
    api("DELETE", "/api/table?slot=test")

    rows = [
        {"id": "r1", "progress": "第一版完成", "insights": "客戶在意延遲", "npi": "5910", "remarks": ""},
        {"id": "r2", "progress": "", "insights": "多行\n也要留住", "npi": "", "remarks": "備註"},
    ]
    saved = api("PUT", "/api/table?slot=test", json={"data": {"v": 1, "rows": rows}, "sha": None})
    assert saved.status_code == 200, saved.text
    assert saved.json()["updated"].endswith("+08:00")

    # PUT 剛成功，緊接著的 GET 有機會讀到寫入前的舊版本，poll 到 sha
    # 對上這次寫入的 sha 才代表讀到的是最新內容。
    response = poll(
        "GET", "/api/table?slot=test", lambda r: r.json().get("sha") == saved.json()["sha"]
    )
    body = response.json()
    assert body["data"]["rows"] == rows
    assert body["sha"] == saved.json()["sha"]


def test_用過期的_sha_寫入會被擋下且不覆蓋(api, poll):
    api("DELETE", "/api/table?slot=test")

    first = api(
        "PUT",
        "/api/table?slot=test",
        json={"data": {"v": 1, "rows": [{"id": "r1", "progress": "原始內容",
                                          "insights": "", "npi": "", "remarks": ""}]},
              "sha": None},
    )
    stale_sha = first.json()["sha"]

    # 模擬另一台裝置先存了一次
    second = api(
        "PUT",
        "/api/table?slot=test",
        json={"data": {"v": 1, "rows": [{"id": "r1", "progress": "別台裝置存的",
                                          "insights": "", "npi": "", "remarks": ""}]},
              "sha": stale_sha},
    )
    fresh_sha = second.json()["sha"]

    conflicted = api(
        "PUT",
        "/api/table?slot=test",
        json={"data": {"v": 1, "rows": [{"id": "r1", "progress": "不該蓋掉別人",
                                          "insights": "", "npi": "", "remarks": ""}]},
              "sha": stale_sha},
    )
    assert conflicted.status_code == 409

    # 關鍵：衝突時資料必須維持別台裝置存的那份。GET 剛好夾在兩次 PUT
    # 之後，一樣有讀到舊版本的空窗期，poll 到 sha 對上第二次寫入才算數。
    response = poll("GET", "/api/table?slot=test", lambda r: r.json().get("sha") == fresh_sha)
    body = response.json()
    assert body["data"]["rows"][0]["progress"] == "別台裝置存的"


def test_正式槽不允許刪除(api):
    """DELETE 只是測試用的工具，絕不能拿來刪正式資料。"""
    response = api("DELETE", "/api/table")
    assert response.status_code == 405


def test_更新時間由伺服器決定而非瀏覽器(api, poll):
    api("DELETE", "/api/table?slot=test")

    put_resp = api(
        "PUT",
        "/api/table?slot=test",
        json={"data": {"v": 1, "updated": "1999-01-01T00:00:00+08:00", "rows": []},
              "sha": None},
    )
    expected_sha = put_resp.json()["sha"]

    response = poll(
        "GET", "/api/table?slot=test", lambda r: r.json().get("sha") == expected_sha
    )
    body = response.json()
    assert not body["data"]["updated"].startswith("1999")
