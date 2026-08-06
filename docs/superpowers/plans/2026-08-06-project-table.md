# 專案追蹤表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有的 Cloudflare Worker 上加一頁可直接編輯的四欄專案追蹤表，資料加密後存進 GitHub。

**Architecture:** 瀏覽器開 `/table.html`，先過既有的 Basic Auth；頁面透過 `/api/table` 讀寫資料。Worker 負責認證、加解密、以及用自己的 GitHub token 把密文 commit 到 `data` 分支。瀏覽器不接觸 token，也不接觸金鑰。

**Tech Stack:** Cloudflare Workers（原生 JS + Web Crypto）、GitHub Contents API、前端原生 HTML/CSS/JS（無框架）、pytest + requests（整合測試）

## Global Constraints

- 規格文件：`docs/superpowers/specs/2026-08-06-project-table-design.md`
- 目標 repo：`micolelin/biweekly-report`，本機路徑 `/Users/admin/git/micolelin/biweekly-report`
- 部署網址：`https://biweekly-report.micole-m-lin.workers.dev`
- 資料分支：`data`；資料檔：分支根目錄的 `table.enc.json`（測試槽為 `table.test.enc.json`）
- 程式碼在 `main` 分支；Cloudflare 盯著 `main` 自動部署，**push 後才會生效**
- 加密規格必須與 `/Users/admin/Documents/m-agent/codelist/dashboard/crypto.py` 完全一致：AES-GCM 256 bit、PBKDF2-HMAC-SHA256 300000 次、salt 16 bytes、iv 12 bytes、封包欄位 `{v, kdf, iter, salt, iv, ct}`、`kdf` 值為字串 `"PBKDF2-SHA256"`
- **每次加密都必須重新產生 salt 與 iv**，不得重複使用
- 缺少任何必要的 Secret 一律拒絕服務（fail closed），不使用預設值
- 任何失敗都要回傳看得懂的錯誤訊息，不得靜默吞掉、不得以空資料代替失敗
- 時間一律台北時間（UTC+8）
- `worker.js` 維持**單一檔案**，不拆模組：本機沒有 Node.js，無法驗證 Cloudflare 的打包是否正確處理 import；打包失敗會讓已上線的報告頁直接掛掉，而且要等部署完才看得出來。以清楚的區段註解代替拆檔
- 註解與訊息一律繁體中文，中文與英數之間留半形空格，沿用 repo 既有風格

---

## 前置作業（人工，一次性）

實作前必須先完成，否則所有測試都會失敗：

1. **建立 `data` 分支**（在本機執行）：

```bash
cd /Users/admin/git/micolelin/biweekly-report
git switch --orphan data
git commit -q --allow-empty -m "chore: 建立資料分支"
git push -u origin data
git switch main
```

2. **Cloudflare 後台**（Workers & Pages → biweekly-report → Settings → Variables and Secrets）新增兩個 Secret：

| 名稱 | 內容 |
|---|---|
| `GH_TOKEN` | GitHub fine-grained token，Repository access 只勾 `micolelin/biweekly-report`，Permissions 只給 `Contents: Read and write` |
| `TABLE_KEY` | 自訂的加密密碼字串，建議 20 字以上隨機字元 |

3. **本機 `.env`**（`/Users/admin/Documents/m-agent/.env`）補上三行，供整合測試使用。前兩項就是現有 Cloudflare 上 `REPORT_USER` / `REPORT_PASSWORD` 的值：

```
REPORT_USER=（現有值）
REPORT_PASSWORD=（現有值）
TABLE_KEY=（與 Cloudflare 上 TABLE_KEY 相同的值）
```

4. 測試執行方式一律為：

```bash
cd /Users/admin/git/micolelin/biweekly-report
set -a && source /Users/admin/Documents/m-agent/.env && set +a
python3 -m pytest tests/integration -v
```

未設定上述環境變數時，整合測試會自動 skip，不影響既有的 85 個離線測試。

---

## 檔案結構

| 檔案 | 責任 | 狀態 |
|---|---|---|
| `worker.js` | 認證（既有）＋ API 路由 ＋ 加解密 ＋ GitHub 讀寫 | 修改 |
| `site/table.html` | 表格頁：顯示、編輯、呼叫 API | 新建 |
| `tests/integration/conftest.py` | 整合測試共用的認證與網址設定 | 新建 |
| `tests/integration/test_table_api.py` | 對已部署的 Worker 做端對端驗證 | 新建 |

`worker.js` 完成後約 350 行，內部以區段註解分為：認證（既有）、加解密、GitHub 儲存、API 路由。

## 測試策略與其限制

本機沒有 Node.js，所以 Worker 的 JavaScript 無法做單元測試。改為用 pytest 打**已部署**的 Worker 做端對端驗證。

為了讓錯誤路徑也測得到，API 支援 `?slot=test` 指向另一個資料檔 `table.test.enc.json`，測試可以自由建立與刪除它，完全不碰正式資料。`DELETE` 只允許用在測試槽。

**測不到、只能靠程式碼審查把關的部分**（實作時要格外小心，並在 PR 說明中指出）：

- 缺少 `GH_TOKEN` / `TABLE_KEY` 時的 fail closed 行為（無法在正式環境製造這個狀態）
- 密文毀損時的解密失敗處理（API 不提供寫入非法密文的途徑）
- 前端在瀏覽器中的實際互動行為

每次改完 `worker.js` 都要 push 才會部署，因此每個任務的驗證步驟都包含「push → 等部署 → 用 `/api/version` 確認新版已上線 → 再跑測試」。

---

### Task 1: API 路由骨架與部署驗證管線

先用一個最小的端點打通「改 code → push → Cloudflare 部署 → pytest 打得到」這條路。這條路不通的話，後面所有任務都無法驗證。同時確認 API 沒有繞過既有認證。

**Files:**
- Modify: `worker.js`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_table_api.py`

**Interfaces:**
- Consumes: 既有的 `isAuthorized(request, env)`
- Produces: `GET /api/version` 回 `{"version": <整數>}`；後續任務每次改 `worker.js` 都要把 `API_VERSION` 加一，測試用它確認新版已部署

- [ ] **Step 1: 建立測試的共用設定**

建立 `tests/integration/conftest.py`。不放 `__init__.py`——測試之間不互相 import，
全部透過 fixture 取得需要的東西，這樣就不必處理 Python 的套件路徑問題：

```python
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
```

- [ ] **Step 2: 寫失敗的測試**

建立 `tests/integration/test_table_api.py`：

```python
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
```

- [ ] **Step 3: 執行測試確認失敗**

```bash
cd /Users/admin/git/micolelin/biweekly-report
set -a && source /Users/admin/Documents/m-agent/.env && set +a
python3 -m pytest tests/integration -v
```

預期：`test_帶帳密時_version_回傳整數版本號` 失敗（目前 `/api/version` 會被當成靜態檔案，回 404 或 HTML）。

- [ ] **Step 4: 在 worker.js 加入路由**

在 `worker.js` 檔案頂端的 `const REALM = ...` 之後加入：

```js
/** 每次改動 worker.js 都要加一。整合測試用它確認新版本已經部署完成。 */
const API_VERSION = 1;
```

把 `export default` 裡 `fetch` 的內容改成（認證那段完全不動，只在通過認證之後、交給靜態檔案之前插入路由）：

```js
export default {
  async fetch(request, env) {
    if (!isAuthorized(request, env)) {
      return new Response('Authentication required to view this report.\n', {
        status: 401,
        headers: {
          'WWW-Authenticate': `Basic realm="${REALM}", charset="UTF-8"`,
          'Content-Type': 'text/plain; charset=utf-8',
          'Cache-Control': 'no-store',
        },
      });
    }

    // 認證通過才進路由，API 因此與頁面共用同一道密碼保護
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/')) {
      return handleApi(request, env, url);
    }

    const response = await env.ASSETS.fetch(request);
    const headers = new Headers(response.headers);
    // 報告內容不該被中介伺服器或搜尋引擎留存
    headers.set('Cache-Control', 'no-store');
    headers.set('X-Robots-Tag', 'noindex, nofollow');
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};

// ===== API 路由 =====

/** 統一的 JSON 回應格式，所有 API 回應都經過這裡。 */
function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}

async function handleApi(request, env, url) {
  if (url.pathname === '/api/version') {
    return jsonResponse({ version: API_VERSION });
  }
  return jsonResponse({ error: `沒有這個端點：${url.pathname}` }, 404);
}
```

- [ ] **Step 5: 部署**

```bash
cd /Users/admin/git/micolelin/biweekly-report
git add worker.js tests/integration
git commit -m "feat(table): API 路由骨架與 /api/version"
git push
```

- [ ] **Step 6: 等待部署完成**

Cloudflare 從 push 到上線約需 1 到 2 分鐘。反覆確認直到版本號出現：

```bash
set -a && source /Users/admin/Documents/m-agent/.env && set +a
curl -s -u "$REPORT_USER:$REPORT_PASSWORD" \
  https://biweekly-report.micole-m-lin.workers.dev/api/version
```

預期最終輸出：`{"version":1}`

若超過 5 分鐘仍未更新，到 Cloudflare 後台看該次部署是否失敗，**不要繼續往下做**。

- [ ] **Step 7: 執行測試確認通過**

```bash
python3 -m pytest tests/integration -v
```

預期：3 個測試全部 PASS。

- [ ] **Step 8: 確認既有測試沒被影響**

```bash
python3 -m pytest -q
```

預期：88 passed（原本 85 個加上新的 3 個）。

- [ ] **Step 9: 確認報告頁沒壞**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -u "$REPORT_USER:$REPORT_PASSWORD" \
  https://biweekly-report.micole-m-lin.workers.dev/
curl -s -o /dev/null -w "%{http_code}\n" \
  https://biweekly-report.micole-m-lin.workers.dev/
```

預期：帶帳密 `200`，未帶帳密 `401`。

---

### Task 2: 加解密與 GitHub 讀取，完成 `GET /api/table`

**Files:**
- Modify: `worker.js`
- Modify: `tests/integration/test_table_api.py`

**Interfaces:**
- Consumes: Task 1 的 `jsonResponse(payload, status)`、`handleApi(request, env, url)`
- Produces:
  - `encryptJson(payload, passphrase) -> Promise<物件>`：回傳 `{v, kdf, iter, salt, iv, ct}` 封包
  - `decryptJson(envelope, passphrase) -> Promise<物件>`
  - `readFile(env, path) -> Promise<{text, sha}>`；檔案不存在時回 `{text: null, sha: null}`
  - `slotName(url) -> 字串`：回傳 `?slot=` 的值，未指定時回 `'main'`
  - `SLOT_FILES` 常數：`{main: 'table.enc.json', test: 'table.test.enc.json'}`，查不到的 slot 代表不合法
  - `GET /api/table[?slot=test]` 回 `{data: {v, updated, rows}, sha}`

- [ ] **Step 1: 寫失敗的測試**

在 `tests/integration/test_table_api.py` 末尾加入：

```python
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
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
python3 -m pytest tests/integration -v
```

預期：三個新測試都失敗（`/api/table` 目前回 404）。

- [ ] **Step 3: 在 worker.js 加入加解密區段**

在 `handleApi` 之後加入：

```js
// ===== 加解密 =====
//
// 規格必須與 m-agent/codelist/dashboard/crypto.py 完全一致，
// 這樣同一份密文兩邊都解得開。改動任一邊都要一起改。

const CRYPTO_VERSION = 1;
const KDF_NAME = 'PBKDF2-SHA256';
const KDF_ITERATIONS = 300000;
const SALT_BYTES = 16;
const IV_BYTES = 12;

function toBase64(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function deriveKey(passphrase, salt, iterations) {
  const material = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(passphrase),
    'PBKDF2',
    false,
    ['deriveKey'],
  );
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations, hash: 'SHA-256' },
    material,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

async function encryptJson(payload, passphrase) {
  // salt 與 iv 每次都重新產生。重複使用 iv 會讓 AES-GCM 的保護整個失效。
  const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const key = await deriveKey(passphrase, salt, KDF_ITERATIONS);
  const plaintext = new TextEncoder().encode(JSON.stringify(payload));
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, plaintext);

  return {
    v: CRYPTO_VERSION,
    kdf: KDF_NAME,
    iter: KDF_ITERATIONS,
    salt: toBase64(salt),
    iv: toBase64(iv),
    ct: toBase64(new Uint8Array(ciphertext)),
  };
}

async function decryptJson(envelope, passphrase) {
  if (envelope.v !== CRYPTO_VERSION) {
    throw new Error(`不支援的封包版本：${envelope.v}`);
  }
  const key = await deriveKey(passphrase, fromBase64(envelope.salt), envelope.iter);
  const plaintext = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: fromBase64(envelope.iv) },
    key,
    fromBase64(envelope.ct),
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}
```

- [ ] **Step 4: 在 worker.js 加入 GitHub 儲存區段**

接在加解密之後：

```js
// ===== GitHub 儲存 =====

const REPO = 'micolelin/biweekly-report';
const DATA_BRANCH = 'data';
// slot 直接參與檔名，所以用白名單而不是過濾字元 —— 白名單不會有漏網之魚
const SLOT_FILES = {
  main: 'table.enc.json',
  test: 'table.test.enc.json',
};

function slotName(url) {
  return url.searchParams.get('slot') || 'main';
}

function githubHeaders(env) {
  return {
    Authorization: `Bearer ${env.GH_TOKEN}`,
    Accept: 'application/vnd.github+json',
    // GitHub API 沒有 User-Agent 會直接拒絕
    'User-Agent': 'biweekly-report-worker',
    'Content-Type': 'application/json',
  };
}

async function readFile(env, path) {
  const response = await fetch(
    `https://api.github.com/repos/${REPO}/contents/${path}?ref=${DATA_BRANCH}`,
    { headers: githubHeaders(env) },
  );

  // 404 代表還沒有這個檔案，是第一次使用的正常狀況，不是錯誤
  if (response.status === 404) return { text: null, sha: null };
  if (!response.ok) {
    throw new Error(`讀取 GitHub 失敗（HTTP ${response.status}）：${await response.text()}`);
  }

  const body = await response.json();
  // GitHub 回的 base64 含換行，atob 不接受，要先清掉
  const raw = fromBase64(body.content.replace(/\n/g, ''));
  return { text: new TextDecoder().decode(raw), sha: body.sha };
}
```

- [ ] **Step 5: 在 worker.js 接上 GET 端點**

把 `handleApi` 換成：

```js
async function handleApi(request, env, url) {
  if (url.pathname === '/api/version') {
    return jsonResponse({ version: API_VERSION });
  }

  if (url.pathname === '/api/table') {
    // 缺任何一個 Secret 都直接拒絕。用預設值硬跑會在「看起來正常」的狀態下
    // 產生解不開的資料，比直接壞掉更難發現。
    if (!env.GH_TOKEN) return jsonResponse({ error: '伺服器未設定 GH_TOKEN' }, 500);
    if (!env.TABLE_KEY) return jsonResponse({ error: '伺服器未設定 TABLE_KEY' }, 500);

    const slot = slotName(url);
    const path = SLOT_FILES[slot];
    if (!path) return jsonResponse({ error: `不合法的 slot：${slot}` }, 400);

    if (request.method === 'GET') return handleGetTable(env, path);
    return jsonResponse({ error: `不支援的方法：${request.method}` }, 405);
  }

  return jsonResponse({ error: `沒有這個端點：${url.pathname}` }, 404);
}

function emptyTable() {
  return { v: 1, updated: null, rows: [] };
}

async function handleGetTable(env, path) {
  let file;
  try {
    file = await readFile(env, path);
  } catch (error) {
    return jsonResponse({ error: String(error.message) }, 502);
  }

  if (file.text === null) {
    return jsonResponse({ data: emptyTable(), sha: null });
  }

  try {
    const data = await decryptJson(JSON.parse(file.text), env.TABLE_KEY);
    return jsonResponse({ data, sha: file.sha });
  } catch (error) {
    // 絕不能在這裡回空表。回空表會讓人以為資料被清掉，接著一存就真的清掉了。
    return jsonResponse(
      { error: `解密失敗，資料未被更動。請確認 TABLE_KEY 是否正確：${error.message}` },
      500,
    );
  }
}
```

- [ ] **Step 6: 把版本號加一並部署**

把 `worker.js` 的 `const API_VERSION = 1;` 改為 `= 2;`，然後：

```bash
git add worker.js tests/integration/test_table_api.py
git commit -m "feat(table): 加解密與 GET /api/table"
git push
```

- [ ] **Step 7: 等待部署到版本 2**

```bash
curl -s -u "$REPORT_USER:$REPORT_PASSWORD" \
  https://biweekly-report.micole-m-lin.workers.dev/api/version
```

反覆執行直到輸出 `{"version":2}`。

- [ ] **Step 8: 執行測試**

```bash
python3 -m pytest tests/integration -v
```

預期：`test_取得表格時回傳資料與_sha` 與 `test_不合法的_slot_被拒絕` PASS。
`test_測試槽的檔案不存在時回空表而非錯誤` 仍會失敗，因為 `DELETE` 還沒實作——這是預期的，它在 Task 3 完成。

若測試槽本來就沒有檔案，該測試也可能直接通過。兩種結果都可以往下走。

---

### Task 3: `PUT` 與 `DELETE`，完成寫入與衝突處理

**Files:**
- Modify: `worker.js`
- Modify: `tests/integration/test_table_api.py`

**Interfaces:**
- Consumes: Task 2 的 `encryptJson`、`readFile`、`slotName`、`SLOT_FILES`、`emptyTable`
- Produces:
  - `writeFile(env, path, text, sha, message) -> Promise<{sha}>`；`sha` 傳 `null` 代表建立新檔
  - `taipeiNow() -> 字串`，格式 `2026-08-06T18:00:00+08:00`
  - `PUT /api/table[?slot=test]`：body `{data, sha}`，回 `{sha, updated}`；sha 不符回 `409`
  - `DELETE /api/table?slot=test`：只允許測試槽，回 `{deleted: true}`

- [ ] **Step 1: 寫失敗的測試**

在 `tests/integration/test_table_api.py` 末尾加入：

```python
def test_寫入後讀得回同樣的內容(api):
    api("DELETE", "/api/table?slot=test")

    rows = [
        {"id": "r1", "progress": "第一版完成", "insights": "客戶在意延遲", "npi": "5910", "remarks": ""},
        {"id": "r2", "progress": "", "insights": "多行\n也要留住", "npi": "", "remarks": "備註"},
    ]
    saved = api("PUT", "/api/table?slot=test", json={"data": {"v": 1, "rows": rows}, "sha": None})
    assert saved.status_code == 200, saved.text
    assert saved.json()["updated"].endswith("+08:00")

    body = api("GET", "/api/table?slot=test").json()
    assert body["data"]["rows"] == rows
    assert body["sha"] == saved.json()["sha"]


def test_用過期的_sha_寫入會被擋下且不覆蓋(api):
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
    api(
        "PUT",
        "/api/table?slot=test",
        json={"data": {"v": 1, "rows": [{"id": "r1", "progress": "別台裝置存的",
                                          "insights": "", "npi": "", "remarks": ""}]},
              "sha": stale_sha},
    )

    conflicted = api(
        "PUT",
        "/api/table?slot=test",
        json={"data": {"v": 1, "rows": [{"id": "r1", "progress": "不該蓋掉別人",
                                          "insights": "", "npi": "", "remarks": ""}]},
              "sha": stale_sha},
    )
    assert conflicted.status_code == 409

    # 關鍵：衝突時資料必須維持別台裝置存的那份
    body = api("GET", "/api/table?slot=test").json()
    assert body["data"]["rows"][0]["progress"] == "別台裝置存的"


def test_正式槽不允許刪除(api):
    """DELETE 只是測試用的工具，絕不能拿來刪正式資料。"""
    response = api("DELETE", "/api/table")
    assert response.status_code == 405


def test_更新時間由伺服器決定而非瀏覽器(api):
    api("DELETE", "/api/table?slot=test")

    api(
        "PUT",
        "/api/table?slot=test",
        json={"data": {"v": 1, "updated": "1999-01-01T00:00:00+08:00", "rows": []},
              "sha": None},
    )

    body = api("GET", "/api/table?slot=test").json()
    assert not body["data"]["updated"].startswith("1999")
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
python3 -m pytest tests/integration -v
```

預期：四個新測試全部失敗（`PUT` 目前回 405）。

- [ ] **Step 3: 在 worker.js 的 GitHub 區段加入寫入與刪除**

接在 `readFile` 之後：

```js
async function writeFile(env, path, text, sha, message) {
  const payload = {
    message,
    content: toBase64(new TextEncoder().encode(text)),
    branch: DATA_BRANCH,
  };
  // 沒有 sha 代表建立新檔。帶著 null 送出去 GitHub 會拒絕，所以只在有值時放進去。
  if (sha) payload.sha = sha;

  const response = await fetch(`https://api.github.com/repos/${REPO}/contents/${path}`, {
    method: 'PUT',
    headers: githubHeaders(env),
    body: JSON.stringify(payload),
  });

  // 409 是 sha 對不上，422 是「檔案已存在但沒給 sha」。兩者都代表同一件事：
  // 這份資料在別的地方被改過了。
  if (response.status === 409 || response.status === 422) {
    const error = new Error('這份資料在別的地方被改過了，請重新載入後再存一次。');
    error.conflict = true;
    throw error;
  }
  if (!response.ok) {
    throw new Error(`寫入 GitHub 失敗（HTTP ${response.status}）：${await response.text()}`);
  }

  const body = await response.json();
  return { sha: body.content.sha };
}

async function deleteFile(env, path) {
  const file = await readFile(env, path);
  if (file.sha === null) return; // 本來就沒有，視為已達成目標

  const response = await fetch(`https://api.github.com/repos/${REPO}/contents/${path}`, {
    method: 'DELETE',
    headers: githubHeaders(env),
    body: JSON.stringify({
      message: 'chore(table): 清除測試資料',
      sha: file.sha,
      branch: DATA_BRANCH,
    }),
  });
  if (!response.ok) {
    throw new Error(`刪除 GitHub 檔案失敗（HTTP ${response.status}）：${await response.text()}`);
  }
}

/** 台北時間，格式 2026-08-06T18:00:00+08:00。 */
function taipeiNow() {
  const shifted = new Date(Date.now() + 8 * 60 * 60 * 1000);
  return `${shifted.toISOString().slice(0, 19)}+08:00`;
}
```

- [ ] **Step 4: 在 handleApi 接上 PUT 與 DELETE**

把 `handleApi` 裡 `/api/table` 那段的方法判斷換成：

```js
    if (request.method === 'GET') return handleGetTable(env, path);
    if (request.method === 'PUT') return handlePutTable(request, env, path);
    if (request.method === 'DELETE') {
      // 刪除只是測試用的工具，正式資料一律不給刪
      if (slot !== 'test') {
        return jsonResponse({ error: '正式資料不提供刪除。' }, 405);
      }
      try {
        await deleteFile(env, path);
        return jsonResponse({ deleted: true });
      } catch (error) {
        return jsonResponse({ error: String(error.message) }, 502);
      }
    }
    return jsonResponse({ error: `不支援的方法：${request.method}` }, 405);
```

並在 `handleGetTable` 之後加入：

```js
async function handlePutTable(request, env, path) {
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: '送出的內容不是合法的 JSON。' }, 400);
  }

  const rows = body?.data?.rows;
  if (!Array.isArray(rows)) {
    return jsonResponse({ error: 'data.rows 必須是陣列。' }, 400);
  }

  // updated 由伺服器決定。瀏覽器的時鐘不可信，而且不同裝置會不一致。
  const data = { v: 1, updated: taipeiNow(), rows };

  try {
    const envelope = await encryptJson(data, env.TABLE_KEY);
    const result = await writeFile(
      env,
      path,
      JSON.stringify(envelope),
      body.sha ?? null,
      `chore(table): 更新專案追蹤表 ${data.updated}`,
    );
    return jsonResponse({ sha: result.sha, updated: data.updated });
  } catch (error) {
    if (error.conflict) return jsonResponse({ error: error.message }, 409);
    return jsonResponse({ error: String(error.message) }, 502);
  }
}
```

- [ ] **Step 5: 把版本號加一並部署**

`API_VERSION` 改為 `3`，然後：

```bash
git add worker.js tests/integration/test_table_api.py
git commit -m "feat(table): PUT 與 DELETE，含 sha 衝突處理"
git push
```

- [ ] **Step 6: 等待部署到版本 3**

```bash
curl -s -u "$REPORT_USER:$REPORT_PASSWORD" \
  https://biweekly-report.micole-m-lin.workers.dev/api/version
```

反覆執行直到輸出 `{"version":3}`。

- [ ] **Step 7: 執行全部整合測試**

```bash
python3 -m pytest tests/integration -v
```

預期：全部 PASS，含 Task 2 那個原本失敗的空表測試。

- [ ] **Step 8: 驗證加密規格（跨語言解密 + salt/iv 每次不同）**

這兩件事只有直接看密文才驗得到，API 本身不會回傳密文。建立暫存腳本 `/tmp/verify_crypto.py`：

```python
"""驗證兩件事：
1. Worker 產生的密文，Python 端解得開（兩邊規格一致）
2. 同樣的內容存兩次，salt 與 iv 都不一樣（重複使用 iv 會讓 AES-GCM 失效）
"""
import base64
import json
import os
import sys

import requests

sys.path.insert(0, "/Users/admin/Documents/m-agent")
from codelist.dashboard import crypto

auth = (os.environ["REPORT_USER"], os.environ["REPORT_PASSWORD"])
base = "https://biweekly-report.micole-m-lin.workers.dev"
rows = [{"id": "x1", "progress": "跨語言驗證", "insights": "", "npi": "", "remarks": ""}]


def read_envelope():
    """直接從 GitHub 抓密文，繞過 Worker 的解密。"""
    response = requests.get(
        "https://api.github.com/repos/micolelin/biweekly-report"
        "/contents/table.test.enc.json?ref=data",
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
        timeout=30,
    )
    response.raise_for_status()
    return json.loads(base64.b64decode(response.json()["content"]).decode("utf-8"))


def put(sha):
    response = requests.put(
        f"{base}/api/table?slot=test",
        auth=auth,
        json={"data": {"v": 1, "rows": rows}, "sha": sha},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["sha"]


requests.delete(f"{base}/api/table?slot=test", auth=auth, timeout=30)

sha = put(None)
first = read_envelope()

decrypted = crypto.decrypt_json(first, os.environ["TABLE_KEY"])
assert decrypted["rows"] == rows, decrypted
print("✅ Python 解得開 Worker 加的密")

put(sha)
second = read_envelope()

assert first["salt"] != second["salt"], "salt 重複了"
assert first["iv"] != second["iv"], "iv 重複了"
print("✅ 每次加密的 salt 與 iv 都不同")
```

執行：

```bash
set -a && source /Users/admin/Documents/m-agent/.env && set +a
python3 /tmp/verify_crypto.py
```

預期輸出兩行 `✅`。確認後刪除暫存腳本：`rm /tmp/verify_crypto.py`

- [ ] **Step 9: 清掉測試資料並確認既有測試沒被影響**

```bash
curl -s -X DELETE -u "$REPORT_USER:$REPORT_PASSWORD" \
  "https://biweekly-report.micole-m-lin.workers.dev/api/table?slot=test"
python3 -m pytest -q
```

預期：全部通過。

---

### Task 4: 表格頁面

**Files:**
- Create: `site/table.html`
- Modify: `tests/integration/test_table_api.py`

**Interfaces:**
- Consumes: Task 3 完成的 `GET` 與 `PUT /api/table`
- Produces: `https://biweekly-report.micole-m-lin.workers.dev/table.html`

- [ ] **Step 1: 寫失敗的測試**

在 `tests/integration/test_table_api.py` 末尾加入：

```python
def test_表格頁需要密碼才打得開(base_url):
    response = requests.get(f"{base_url}/table.html", timeout=30)
    assert response.status_code == 401


def test_表格頁帶帳密時送得出來(api):
    response = api("GET", "/table.html")
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    # 四個欄位的標題都要在頁面裡
    for label in ("Progress", "Insights", "NPI", "Remarks"):
        assert label in response.text
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
python3 -m pytest tests/integration -v -k 表格頁
```

預期：`test_表格頁帶帳密時送得出來` 失敗（頁面還不存在）。

- [ ] **Step 3: 建立 site/table.html**

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>專案追蹤表</title>
<style>
  :root {
    --bg: #f0f2f5; --fg: #1a1a2e; --card: #ffffff; --muted: #6b7280;
    --line: #e5e7eb; --accent: #1e40af; --danger: #dc2626; --ok: #16a34a;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f172a; --fg: #e2e8f0; --card: #1e293b; --muted: #94a3b8;
      --line: #334155; --accent: #60a5fa; --danger: #f87171; --ok: #4ade80;
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg); color: var(--fg);
    /* 為底部固定狀態列留位置，否則最後一列會被蓋住 */
    padding-bottom: 5rem;
  }
  header {
    background: var(--card); border-bottom: 1px solid var(--line);
    padding: 0.75rem 1rem; position: sticky; top: 0; z-index: 10;
  }
  header h1 { font-size: 1.05rem; font-weight: 700; }
  main { padding: 1rem; max-width: 80rem; margin: 0 auto; }

  table { width: 100%; border-collapse: collapse; background: var(--card); }
  th, td { border: 1px solid var(--line); padding: 0.5rem; vertical-align: top; text-align: left; }
  th { font-size: 0.85rem; color: var(--muted); font-weight: 600; }
  textarea {
    width: 100%; border: none; background: transparent; color: inherit;
    font: inherit; resize: none; overflow: hidden; min-height: 2.5rem;
  }
  textarea:focus { outline: 2px solid var(--accent); outline-offset: 2px; }
  .row-tools { width: 3rem; text-align: center; }
  .del {
    background: none; border: none; color: var(--muted);
    font-size: 1.1rem; cursor: pointer; padding: 0.25rem 0.5rem;
  }
  .del:hover { color: var(--danger); }

  /* 手機：四欄文字擠進一個螢幕必然不可讀，改成一列一張卡片 */
  @media (max-width: 40rem) {
    thead { display: none; }
    table, tbody, tr, td { display: block; width: 100%; }
    tr {
      background: var(--card); border: 1px solid var(--line);
      border-radius: 0.75rem; margin-bottom: 1rem; padding: 0.5rem;
    }
    td { border: none; border-bottom: 1px solid var(--line); padding: 0.5rem 0.25rem; }
    td:last-of-type { border-bottom: none; }
    td::before {
      content: attr(data-label); display: block;
      font-size: 0.75rem; color: var(--muted); font-weight: 600; margin-bottom: 0.25rem;
    }
    .row-tools { text-align: right; }
  }

  #bar {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: var(--card); border-top: 1px solid var(--line);
    padding: 0.75rem 1rem; display: flex; align-items: center;
    gap: 0.75rem; flex-wrap: wrap;
  }
  #status { flex: 1; font-size: 0.9rem; color: var(--muted); min-width: 10rem; }
  #status.error { color: var(--danger); }
  #status.saved { color: var(--ok); }
  button.action {
    background: var(--accent); color: #fff; border: none;
    border-radius: 0.5rem; padding: 0.6rem 1rem;
    font: inherit; font-weight: 600; cursor: pointer;
  }
  button.action[disabled] { opacity: 0.5; cursor: default; }
  button.ghost { background: transparent; color: var(--accent); border: 1px solid var(--line); }
</style>
</head>
<body>
<header><h1>專案追蹤表</h1></header>

<main>
  <table>
    <thead>
      <tr>
        <th>Progress</th><th>Insights</th><th>NPI</th><th>Remarks</th><th class="row-tools"></th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
</main>

<div id="bar">
  <span id="status">載入中…</span>
  <button class="action ghost" id="add">＋ 新增一列</button>
  <button class="action" id="save" disabled>儲存</button>
</div>

<script>
const FIELDS = ['progress', 'insights', 'npi', 'remarks'];
const LABELS = { progress: 'Progress', insights: 'Insights', npi: 'NPI', remarks: 'Remarks' };

let rows = [];
let sha = null;
let dirty = false;

const $rows = document.getElementById('rows');
const $status = document.getElementById('status');
const $save = document.getElementById('save');

function setStatus(text, kind = '') {
  $status.textContent = text;
  $status.className = kind;
}

function markDirty() {
  dirty = true;
  $save.disabled = false;
  setStatus('未儲存');
}

/** 每列一個穩定 id，刪掉中間某列時其他列不會錯位。 */
function newId() {
  return Math.random().toString(36).slice(2, 10);
}

function autoGrow(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function render() {
  $rows.textContent = '';
  for (const row of rows) {
    const tr = document.createElement('tr');

    for (const field of FIELDS) {
      const td = document.createElement('td');
      td.dataset.label = LABELS[field];
      const textarea = document.createElement('textarea');
      textarea.value = row[field] || '';
      textarea.addEventListener('input', () => {
        row[field] = textarea.value;
        autoGrow(textarea);
        markDirty();
      });
      td.appendChild(textarea);
      tr.appendChild(td);
    }

    const tools = document.createElement('td');
    tools.className = 'row-tools';
    const del = document.createElement('button');
    del.className = 'del';
    del.textContent = '✕';
    del.title = '刪除這一列';
    del.addEventListener('click', () => {
      if (!confirm('刪除這一列？')) return;
      rows = rows.filter((candidate) => candidate.id !== row.id);
      render();
      markDirty();
    });
    tools.appendChild(del);
    tr.appendChild(tools);

    $rows.appendChild(tr);
  }

  // 內容塞進 DOM 之後才量得到高度
  for (const textarea of $rows.querySelectorAll('textarea')) autoGrow(textarea);
}

async function load() {
  setStatus('載入中…');
  try {
    const response = await fetch('/api/table');
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);

    // id 一定要放在展開之後：舊資料若沒有 id，展開會用 undefined 蓋掉剛產生的 id
    rows = body.data.rows.map((row) => ({ ...row, id: row.id || newId() }));
    sha = body.sha;
    render();
    dirty = false;
    $save.disabled = true;
    setStatus(body.data.updated ? `已儲存 ${body.data.updated.slice(11, 16)}` : '尚無資料', 'saved');
  } catch (error) {
    // 載入失敗時不要顯示空表格，那會讓人以為資料不見了
    setStatus(`載入失敗：${error.message}`, 'error');
  }
}

async function save() {
  $save.disabled = true;
  setStatus('儲存中…');
  try {
    const response = await fetch('/api/table', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: { v: 1, rows }, sha }),
    });
    const body = await response.json();

    if (response.status === 409) {
      // 衝突時絕不清空畫面 —— 使用者剛打的字必須留著
      setStatus(body.error, 'error');
      $save.disabled = false;
      return;
    }
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);

    sha = body.sha;
    dirty = false;
    setStatus(`已儲存 ${body.updated.slice(11, 16)}`, 'saved');
  } catch (error) {
    setStatus(`儲存失敗：${error.message}`, 'error');
    $save.disabled = false;
  }
}

document.getElementById('add').addEventListener('click', () => {
  rows.push({ id: newId(), progress: '', insights: '', npi: '', remarks: '' });
  render();
  markDirty();
});

$save.addEventListener('click', save);

window.addEventListener('beforeunload', (event) => {
  if (!dirty) return;
  event.preventDefault();
  event.returnValue = '';
});

load();
</script>
</body>
</html>
```

- [ ] **Step 4: 部署**

`API_VERSION` 改為 `4`（新增頁面也要能確認部署完成），然後：

```bash
git add site/table.html worker.js tests/integration/test_table_api.py
git commit -m "feat(table): 專案追蹤表頁面"
git push
```

- [ ] **Step 5: 等待部署到版本 4**

```bash
curl -s -u "$REPORT_USER:$REPORT_PASSWORD" \
  https://biweekly-report.micole-m-lin.workers.dev/api/version
```

反覆執行直到輸出 `{"version":4}`。

- [ ] **Step 6: 執行測試**

```bash
python3 -m pytest tests/integration -v
```

預期：全部 PASS。

- [ ] **Step 7: 人工驗收**

用瀏覽器開 `https://biweekly-report.micole-m-lin.workers.dev/table.html`，輸入帳密後逐項確認：

1. 按「＋ 新增一列」出現空白列，狀態列變成「未儲存」
2. 四個格子都能輸入，打多行時格子會自己長高
3. 按「儲存」後狀態列變成「已儲存 HH:MM」
4. 重新整理，剛才打的內容還在
5. 刪除某一列會跳確認框，取消則不刪
6. **刪除中間那列的驗證**：建立三列，內容分別填 A、B、C 後儲存；刪掉 B 再儲存；
   重新整理後應該只剩 A 與 C，且內容沒有互相錯位
7. **衝突的驗證**：在兩個分頁同時開這一頁，分頁一改內容並儲存；
   接著在分頁二（拿的是舊 sha）改內容並儲存。分頁二應該顯示紅色的「資料在別的地方被改過」，
   而且**剛打的字還留在畫面上沒有被清掉**
8. 有未儲存內容時關閉分頁，瀏覽器會攔截提示
9. 手機開同一個網址，每列顯示為卡片、四個欄位有標籤直排，畫面不會左右跑
10. 深色模式下文字看得清楚

第 6、7 項是規格裡明列、但整合測試碰不到的行為，一定要人工走過。

- [ ] **Step 8: 確認報告頁與既有測試都沒被影響**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -u "$REPORT_USER:$REPORT_PASSWORD" \
  https://biweekly-report.micole-m-lin.workers.dev/
python3 -m pytest -q
```

預期：`200`，測試全過。

---

### Task 5: 收尾

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 清除測試資料**

```bash
set -a && source /Users/admin/Documents/m-agent/.env && set +a
curl -s -X DELETE -u "$REPORT_USER:$REPORT_PASSWORD" \
  "https://biweekly-report.micole-m-lin.workers.dev/api/table?slot=test"
```

- [ ] **Step 2: 在 README.md 補上說明**

在 `README.md` 最末尾附加一節：

```markdown
## 專案追蹤表

網址：<https://biweekly-report.micole-m-lin.workers.dev/table.html>（與報告頁同一組帳密）

四欄自由文字（Progress / Insights / NPI / Remarks），一列一個專案。按「儲存」才會寫回，
每次儲存等於一個 commit。

資料存放：`data` 分支的 `table.enc.json`，以 AES-GCM 加密，金鑰是 Cloudflare Secret `TABLE_KEY`。
瀏覽器不接觸 GitHub token 也不接觸金鑰，加解密都在 Worker 內完成。

與雙週記錄（`data/entries/`）完全獨立，兩者不共用資料。

### 相關 Secret

| 名稱 | 用途 |
|---|---|
| `GH_TOKEN` | Worker 寫入 data 分支用的 GitHub token |
| `TABLE_KEY` | 表格資料的加密金鑰 |

### 測試

整合測試打的是已部署的 Worker，需要 `REPORT_USER` / `REPORT_PASSWORD`：

    set -a && source /Users/admin/Documents/m-agent/.env && set +a
    python3 -m pytest tests/integration -v

未設定時會自動 skip。寫入類測試一律使用 `?slot=test`，不會碰到正式資料。
```

- [ ] **Step 3: 執行完整測試**

```bash
python3 -m pytest -q
```

預期：全部通過。

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: 補上專案追蹤表說明"
git push
```

- [ ] **Step 5: 最終確認**

```bash
curl -s -o /dev/null -w "report=%{http_code}\n" -u "$REPORT_USER:$REPORT_PASSWORD" \
  https://biweekly-report.micole-m-lin.workers.dev/
curl -s -o /dev/null -w "table=%{http_code}\n" -u "$REPORT_USER:$REPORT_PASSWORD" \
  https://biweekly-report.micole-m-lin.workers.dev/table.html
curl -s -o /dev/null -w "anon=%{http_code}\n" \
  https://biweekly-report.micole-m-lin.workers.dev/table.html
```

預期：`report=200`、`table=200`、`anon=401`
