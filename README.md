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
