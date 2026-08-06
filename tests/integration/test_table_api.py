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
