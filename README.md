# 雙週工作報告系統

每兩週給主管一份工作報告。平常隨手把工作內容記進工作台，兩週一次按一個按鈕由 AI 彙整成草稿，編修後發布成網頁，寄連結給主管。

取代原本「寄信夾附件」的做法 —— 附件要下載才看得到，信件容易被埋掉。改成信件內文只放 3 行重點加一個連結，網頁承載完整內容。

## 三層架構

| 層 | 做什麼 | 跑在哪 |
|---|---|---|
| 記錄層 | Streamlit 工作台，隨手記、上傳附件 | 本機或 Streamlit Cloud |
| 資料層 | 所有記錄、附件、報告 | 本 repo 的 `data/`，透過 GitHub API 讀寫 |
| 呈現層 | 靜態報告頁（本期／歷史／趨勢對照） | Cloudflare Pages |

**本機零檔案**：工作台不在本機保留任何資料副本，所有讀寫直接對 GitHub 進行。這讓工作台跑在哪台機器上都一樣，也是它能部署上雲的前提。

## 資料放哪

```
data/
  config.json              類別清單、期別錨定日、主管 email（選填）、發布網址
  entries/YYYY-MM/         每筆記錄一個 .md，含 YAML frontmatter
  attachments/YYYY-MM/     上傳的原始檔
  published/YYYY-MM-DD/    每期報告（report.md 原稿 + index.html 成品）
```

用純文字檔而不是資料庫：檔案可以直接在 GitHub 網頁上打開來看、可以全文搜尋、有版本歷史，程式壞掉資料也不會陪葬。

寫入走 **GitHub Git Data API** 而非 Contents API —— 後者以 base64 寫入時實務上限約 1 MB，PPT、Excel 附件必然超過。Git Data API 上限 100 MB，且能把「一筆記錄 + 多個附件」包成單一 commit。

## 本機執行

```bash
cd /Users/admin/git/micolelin/biweekly-report
set -a && source /Users/admin/Documents/m-agent/.env && set +a
python3 -m streamlit run app.py
```

## 部署到 Streamlit Community Cloud

1. <https://share.streamlit.io> 用 GitHub 帳號登入
2. 選這個 repo，主檔案填 `app.py`
3. 在 **Secrets** 欄位填入下列四個鍵（值不要寫進任何檔案）：

```toml
GITHUB_TOKEN = "..."
GEMINI_API_KEY = "..."
GROQ_API_KEY = "..."
ANTHROPIC_API_KEY = "..."
```

4. 把 app 設為 **private**，並把自己的 email 加進 viewer 名單

### GITHUB_TOKEN 請用細粒度權限

在 <https://github.com/settings/personal-access-tokens/new> 產生，並且：

- Repository access 選 **Only select repositories**，只勾這個 repo
- Permissions → Repository permissions → **Contents** 設為 **Read and write**
- 其他權限一律不給

**不要沿用能存取其他 repo 的舊 token。** 這把鑰匙要交給第三方服務保管，權限給到剛好夠用就好 —— 萬一外流，對方拿到的只有這個 repo 的報告資料。

### 已知限制

Streamlit Community Cloud 免費方案的 app **12 小時沒有流量就會休眠**。兩週用一次的話，每次點進去要等 30 秒到 1 分鐘喚醒。

## 報告頁的存取保護

報告頁部署在 Cloudflare Workers，由 `worker.js` 以 HTTP Basic 認證擋下未授權存取。主管點連結會跳出瀏覽器內建的帳號密碼框，**不需要註冊任何帳號**。

沒有採用 Cloudflare Zero Trust Access 的原因：它的免費方案要求綁定付款方式（實測確認，即使顯示 $0/month）。

### 設定帳號

在 Cloudflare 儀表板 → 該 Worker → Settings → Variables and Secrets，新增 **Secret**：

單一組（最簡單）：

| 名稱 | 值 |
|---|---|
| `REPORT_USER` | 帳號 |
| `REPORT_PASSWORD` | 密碼 |

多組（要給不同人不同帳號時用）：

| 名稱 | 值 |
|---|---|
| `REPORT_ACCOUNTS` | 一行一組，格式 `帳號:密碼` |

```
manager:主管的密碼
colleague:同事的密碼
```

兩種可以並存。空行與 `#` 開頭的行會被略過。密碼本身可以含冒號（只切第一個）。

**分開發帳號的好處**：要停用某個人時，把那一行刪掉就好，其他人不受影響、也不用通知他們改密碼。

密碼請用英數字 —— Basic 認證對非 ASCII 字元的處理各家瀏覽器不一致。

### 兩個關鍵安全設計

**`wrangler.jsonc` 的 `assets.run_worker_first` 必須是 `true`。** 否則 Cloudflare 會直接送出靜態檔案而根本不執行 `worker.js`，密碼形同虛設 —— 而且從外面完全看不出來。

**一組帳號都沒設時，一律拒絕所有人。** 相反的做法（沒設就放行）會讓人以為有保護，實際上整份報告公開在網路上。打不開是安全的失敗，看得到才是災難。

## 彙整引擎

支援三個供應商，可在「產生報告」分頁直接切換：

| 供應商 | 模型 | 環境變數 |
|---|---|---|
| gemini（預設） | `gemini-flash-latest` | `GEMINI_API_KEY` |
| groq | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| anthropic | `claude-opus-5` | `ANTHROPIC_API_KEY` |

**不做自動 fallback。** 某個供應商失敗時會明確報錯並指名是哪一個，不會默默改用別的 —— 否則你不會知道自己選的服務壞了。

### 不可妥協的一條原則

`summarize.SYSTEM_PROMPT` 明確禁止 AI 加入原始記錄中不存在的資訊、禁止推測、禁止美化成果，素材不足時要寫「本期無」而非自行填充。

報告中每一句都必須能追回到某一筆原始記錄。這份文件會直接送到主管眼前，只要有一句是編造的，承擔後果的是寫報告的人。修改這段提示前請想清楚。

有兩個測試守著它不被誤刪：`test_系統提示明確禁止捏造內容`、`test_系統提示要求四個固定段落`。

## 測試

```bash
python3 -m pytest biweekly/tests/ -v
```

UI（`app.py`）沒有自動化測試 —— Streamlit 介面難以自動驗證，因此所有商業邏輯都放在 `biweekly/` 底下的模組並有測試覆蓋，UI 層只做組裝與錯誤呈現。

## 設計上刻意的取捨

- **報告頁零外部資源**（CSS、字型全部內嵌）：主管兩週才點一次，開啟速度是成敗關鍵。
- **不自動寄信**：公司信件系統通常阻擋第三方程式寄送。工作台產生可直接複製的信件內容，使用者貼進 Outlook 送出。
- **儲存失敗時輸入框內容不清空**：資料全在雲端，斷網就存不了。若按下儲存後跳錯又被清空，剛打完的內容就沒了。清空只發生在成功路徑，靠更換 widget key 達成（不能用 `st.form(clear_on_submit=True)`，那會不分成敗一律清空）。
- **趨勢對照頁不做數值圖表**：內容以文字為主且形式不固定，硬做圖表會失真。改為把各期的「本期重點」與「問題與需要協助」並列，讓主管看出哪些問題延續多期。窄螢幕會自動改為卡片堆疊。

## 專案追蹤表

網址：<https://biweekly-report.micole-m-lin.workers.dev/table>（與報告頁同一組帳密，開啟時會跳出瀏覽器內建的帳號密碼框）

一張隨時可以打開來改的表格，一列一個專案，四個欄位：Progress／Insights／NPI／Remarks，內容會持續改寫而不是流水帳。窄螢幕（手機）會自動改成一列一張卡片。按「儲存」才會真正寫回，每次儲存等於一筆 git commit，所以改動有歷史可查。跟雙週報告用的記錄（`data/entries/`）完全是兩份獨立資料，互不相通。

多裝置同時編輯時，後儲存的一方會被擋下並提示「這份資料在別的地方被改過了，請重新載入」，不會被悄悄覆蓋掉——但也不會自動合併，需要自己決定要不要重新載入再改一次。

### 給維護者的技術細節

資料存放在本 repo 的 `data` 分支（`table.enc.json`），與 `main` 分開是為了避免每次存檔都觸發 Cloudflare 重新部署。內容以 AES-GCM 加密，金鑰是 Cloudflare Secret `TABLE_KEY`；瀏覽器全程不接觸 GitHub token 也不接觸加密金鑰，加解密都在 `worker.js` 裡完成。金鑰導出用 PBKDF2-HMAC-SHA256、**100,000 次疊代**（Cloudflare Workers 對 PBKDF2 的硬性上限，超過會直接丟錯；為什麼這個數字仍然安全，見設計規格）。完整設計與取捨寫在 [`docs/superpowers/specs/2026-08-06-project-table-design.md`](docs/superpowers/specs/2026-08-06-project-table-design.md)。

相關 Secret：

| 名稱 | 用途 |
|---|---|
| `GH_TOKEN` | Worker 寫入 data 分支用的 GitHub token |
| `TABLE_KEY` | 表格資料的加密金鑰 |

### 測試

```bash
set -a && source /Users/admin/Documents/m-agent/.env && set +a
python3 -m pytest tests/integration -v
```

沒設 `REPORT_USER` / `REPORT_PASSWORD` 時會自動 skip，預設的 `pytest` 完全離線。寫入類測試一律使用 `?slot=test`，不會碰到正式資料。

**不要同時跑兩份這個測試套件。** 所有測試共用同一個 `slot=test` 資料檔，兩個 run 同時進行會互相覆蓋對方寫入的狀態，跑出來的失敗看起來像 API 或邏輯壞了，其實只是撞在一起。想跑就一次跑完、跑完再跑下一次。
