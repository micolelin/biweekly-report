# 專案追蹤表設計規格

日期：2026-08-06
狀態：已核准，待實作

## 目的

一張網頁上直接編輯的表格，追蹤各專案的狀態。四個欄位：progress、insights、NPI、remarks。
每一列代表一個專案／主題，內容會被持續改寫，不是流水帳。

這張表與現有的雙週記錄（`data/entries/`）**完全獨立**，各自有各自的資料，互不讀寫。
雖然雙週記錄的分類恰好也叫 Insights / Progress / NPI，但兩者不共用資料、不同步。

## 範圍外

- 不改動現有的 Streamlit 工作台
- 不改動現有的雙週記錄資料與流程
- 不做多人協作、留言、歷史版本瀏覽（git 歷史本身就是版本紀錄）
- 不做欄位自訂：四欄固定

## 架構

```
瀏覽器 ──Basic Auth──> Cloudflare Worker ──GitHub API──> micolelin/biweekly-report
  表格頁                  加解密 + 讀寫                      data 分支
```

三個單元，各自職責清楚：

| 單元 | 職責 | 依賴 |
|---|---|---|
| `site/table.html` | 顯示與編輯表格，呼叫兩個 API | 只依賴 API 的 JSON 形狀 |
| `worker.js` 的 API 層 | 認證、加解密、讀寫 GitHub | Cloudflare Secret、GitHub API |
| 加解密模組 | 明文 ⇄ 密文封包 | Web Crypto |

前端完全不知道資料存在 GitHub，也不知道有加密這回事；換掉後端儲存不需要動前端。

### 檔案位置

| 東西 | 路徑 |
|---|---|
| 頁面 | `site/table.html`（main 分支） |
| 資料 | `table.enc.json`（**data 分支**根目錄） |
| Worker | `worker.js`（main 分支，擴充現有檔案） |

網址：`https://biweekly-report.micole-m-lin.workers.dev/table.html`

**資料為什麼放 data 分支**：Cloudflare 盯著 `main` 自動部署。若每次存檔都往 `main` commit，
等於每存一次就觸發一次 Worker 重新部署——白燒建置額度，且存檔當下 Worker 可能正在重啟。
放獨立分支完全避開這個問題，同時保留 git 的版本歷史。

## 資料流

**讀取**

1. 瀏覽器開 `/table.html` → Worker 的 Basic Auth 擋一次（現有機制，不修改）
2. 頁面載入後打 `GET /api/table`
3. Worker 用 `GH_TOKEN` 從 data 分支讀 `table.enc.json`
4. 用 `TABLE_KEY` 解密，回傳明文 JSON 與該檔案的 GitHub sha

**寫入**

1. 使用者按儲存，頁面 `PUT /api/table`，body 帶明文 JSON 與讀取時拿到的 sha
2. Worker 用 `TABLE_KEY` 加密
3. 用 GitHub Contents API commit 到 data 分支，帶上 sha

瀏覽器從頭到尾不接觸 GitHub token，也不接觸加密金鑰。

## 資料結構

```json
{
  "v": 1,
  "updated": "2026-08-06T18:00:00+08:00",
  "rows": [
    { "id": "a3f1c2", "progress": "", "insights": "", "npi": "", "remarks": "" }
  ]
}
```

- `v`：結構版本。日後改結構時用來判斷是否需要轉換
- `updated`：台北時間 ISO 8601，由 Worker 在寫入時填入（不信任瀏覽器的時鐘）
- `id`：每列一個穩定識別碼，前端產生。用途是刪除中間某列時其他列不會錯位
- 四個內容欄一律是字串，允許多行；空字串代表未填

檔案不存在時（第一次使用），`GET` 回傳 `rows: []` 與 `sha: null`，不視為錯誤。

## API

Worker 在把請求交給靜態檔案之前先攔截 `/api/` 開頭的路徑。
認證檢查在路由之前，兩個端點與頁面共用同一道 Basic Auth。

### `GET /api/table`

回應 `200`：

```json
{ "data": { "v": 1, "updated": "…", "rows": [...] }, "sha": "abc123…" }
```

### `PUT /api/table`

請求：

```json
{ "data": { "v": 1, "rows": [...] }, "sha": "abc123…" }
```

回應 `200`：`{ "sha": "def456…", "updated": "…" }`

錯誤回應一律是 `{ "error": "看得懂的中文訊息" }`，搭配對應狀態碼。

## 衝突處理

讀取時拿到的 sha 會在寫入時帶回去。若期間有別的裝置存過，GitHub 會拒絕該次寫入，
Worker 回 `409` 與明確訊息。

**衝突時一律不覆蓋**，前端顯示「這份資料在別的地方被改過了，請重新載入」，
並保留使用者當下的輸入內容（不要清空，否則會吃掉剛打的字）。
使用者自行決定是否重新載入。不做自動合併——四欄自由文字沒有可靠的合併規則。

## 錯誤處理

原則：**任何失敗都要看得見，絕不靜默吞掉**。

| 狀況 | 行為 |
|---|---|
| 缺 `GH_TOKEN` 或 `TABLE_KEY` | Worker 回 `500` 與明確訊息，不使用任何預設值（fail closed，與現有 Basic Auth 同原則） |
| GitHub API 失敗 | Worker 回 `502`，訊息含 GitHub 的回應 |
| 解密失敗（金鑰不對／檔案毀損） | Worker 回 `500`，明講是解密失敗，**不回傳空表**——回空表會讓使用者以為資料被清掉，接著存檔就真的清掉了 |
| sha 衝突 | `409`，見上節 |
| 前端呼叫失敗 | 狀態列顯示紅色錯誤訊息，保留使用者輸入 |

## 前端行為

**桌機**：四欄表格，每格是隨內容自動長高的輸入框。

**手機**（窄螢幕）：一列變一張卡片，四個欄位加標籤直排。
四欄自由文字擠進手機寬度必然不可讀，所以換版型而非橫向捲動。

**共通**

- 底部固定狀態列：`未儲存` / `儲存中…` / `已儲存 18:03` / 錯誤訊息
- 狀態列旁有「＋ 新增一列」
- 每列有刪除鈕，按下需確認
- 有未儲存變更時離開頁面會攔截提示
- 儲存為手動觸發（按鈕）。不做自動儲存——每次存都是一個 commit，自動存會把 git 歷史洗爛
- 樣式沿用現有 `site/index.html` 的視覺，支援淺色與深色

## 加密

規格與 `m-agent/codelist/dashboard/crypto.py` 對齊，日後 Python 端也解得開：

| 項目 | 值 |
|---|---|
| 對稱加密 | AES-GCM，256 bit |
| 金鑰導出 | PBKDF2-HMAC-SHA256，300,000 次 |
| salt | 16 bytes，每次加密重新產生 |
| iv | 12 bytes，每次加密重新產生 |

封包格式（與 `crypto.py` 相同）：

```json
{ "v": 1, "kdf": "PBKDF2-SHA256", "iter": 300000, "salt": "…", "iv": "…", "ct": "…" }
```

Worker 端用 Web Crypto 實作。**salt 與 iv 每次寫入都必須重新產生**，重複使用 iv 會讓 AES-GCM 的安全性失效。

## 設定

需要在 Cloudflare 後台新增兩個 Secret：

| 名稱 | 內容 |
|---|---|
| `GH_TOKEN` | GitHub 細粒度 token，只能存取 `micolelin/biweekly-report`，權限只給 Contents 讀寫 |
| `TABLE_KEY` | 加密用密碼字串 |

另需在 GitHub 建立 `data` 分支（可為空分支）。

現有的 `REPORT_USER` / `REPORT_PASSWORD` 不變，表格頁沿用同一組。

## 測試

**Worker**

- 加解密 round-trip：加密後解密得回原始物件
- 每次加密產生不同的 salt 與 iv
- 未帶 Basic Auth 時 `/api/table` 回 `401`（API 不能繞過既有認證）
- 缺 `GH_TOKEN` 或 `TABLE_KEY` 時回 `500` 而非用預設值繼續
- 檔案不存在時 `GET` 回空表與 `sha: null`
- sha 不符時 `PUT` 回 `409` 且未寫入
- 解密失敗時回 `500` 而非空表

**前端**

- 刪除中間某列後，其餘各列的內容仍對應到正確的 id
- 衝突回應後使用者輸入未被清空

## 已知風險

`micolelin/biweekly-report` 目前是**公開** repo（GitHub 回報 `visibility: public`），
現有的 `data/entries/` 明文記錄任何人都讀得到。本設計的表格資料有加密所以不受影響，
但既有記錄的曝露問題尚未處理——使用者已知悉，決定先做表格。
