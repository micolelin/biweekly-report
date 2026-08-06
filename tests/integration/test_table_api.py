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


def test_測試槽的檔案不存在時回空表而非錯誤(api):
    """第一次使用時沒有資料檔，這是正常狀況不是錯誤。"""
    api("DELETE", "/api/table?slot=test")

    response = api("GET", "/api/table?slot=test")
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
