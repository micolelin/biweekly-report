"""測試用的假 HTTP 物件，讓測試完全不碰真實網路。"""
import json


class FakeResponse:
    """模擬 requests 的 Response。"""

    def __init__(self, payload=None, status_code=200, content=b""):
        self._payload = {} if payload is None else payload
        self.status_code = status_code
        self.content = content
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}：{self.text}")


class FakeSession:
    """依 (HTTP 方法, 網址結尾) 對照表回應，並記錄所有呼叫供斷言。

    routes 的形式：{("GET", "git/ref/heads/main"): FakeResponse(...)}
    """

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []
        self.headers = {}

    def _handle(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get("json")))
        for (route_method, suffix), response in self.routes.items():
            if route_method == method and url.endswith(suffix):
                return response
        raise AssertionError(f"沒有為 {method} {url} 準備假回應")

    def get(self, url, **kwargs):
        return self._handle("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._handle("POST", url, **kwargs)

    def patch(self, url, **kwargs):
        return self._handle("PATCH", url, **kwargs)

    def json_bodies(self, method, suffix):
        """取出符合條件的呼叫送出的 JSON body 清單。"""
        return [
            body
            for call_method, url, body in self.calls
            if call_method == method and url.endswith(suffix)
        ]
