from biweekly import render

SAMPLE = """## 本期重點

- 完成 TCO 試算表

## 進度細節

跟客戶開了兩次會。

## 問題與需要協助

需要主管協助爭取樣品。

## 下期計畫

送樣。
"""


def test_取出指定段落的內容():
    assert "完成 TCO 試算表" in render.extract_section(SAMPLE, "本期重點")


def test_取出的段落不含下一個段落的內容():
    section = render.extract_section(SAMPLE, "本期重點")
    assert "跟客戶開了兩次會" not in section


def test_取出最後一個段落也正常():
    assert "送樣" in render.extract_section(SAMPLE, "下期計畫")


def test_段落不存在時回傳空字串():
    assert render.extract_section(SAMPLE, "不存在的段落") == ""


def test_網頁含三個分頁():
    html = render.render_site([render.Report(label="2026-08-14", markdown=SAMPLE)])
    assert "本期" in html
    assert "歷史" in html
    assert "趨勢對照" in html


def test_網頁把_Markdown_轉成_HTML():
    html = render.render_site([render.Report(label="2026-08-14", markdown=SAMPLE)])
    assert "<h2" in html
    assert "完成 TCO 試算表" in html


def test_網頁不引用任何外部資源():
    html = render.render_site([render.Report(label="2026-08-14", markdown=SAMPLE)])
    assert "http://" not in html
    assert "https://" not in html


def test_歷史頁列出所有期別():
    reports = [
        render.Report(label="2026-08-28", markdown=SAMPLE),
        render.Report(label="2026-08-14", markdown=SAMPLE),
    ]
    html = render.render_site(reports)
    assert "2026-08-28" in html
    assert "2026-08-14" in html


def _trend_block(html: str) -> str:
    """只取出 id="trend" 這個 section 自己的內容，不含後面（或前面重排後）的其他區塊。"""
    trend_start = html.index('id="trend"')
    trend_end = html.index("</section>", trend_start)
    return html[trend_start:trend_end]


def test_趨勢對照只取重點與問題兩段():
    reports = [render.Report(label="2026-08-14", markdown=SAMPLE)]
    html = render.render_site(reports)
    trend_block = _trend_block(html)
    assert "需要主管協助爭取樣品" in trend_block
    assert "跟客戶開了兩次會" not in trend_block


def test_趨勢對照多期並列時各期的重點與問題都在():
    sample_2 = """## 本期重點

- 完成客戶簡報

## 進度細節

內部對齊了規格。

## 問題與需要協助

需要法務協助審合約。

## 下期計畫

簽約。
"""
    reports = [
        render.Report(label="2026-08-28", markdown=sample_2),
        render.Report(label="2026-08-14", markdown=SAMPLE),
    ]
    html = render.render_site(reports)
    trend_block = _trend_block(html)
    assert "完成 TCO 試算表" in trend_block
    assert "需要主管協助爭取樣品" in trend_block
    assert "完成客戶簡報" in trend_block
    assert "需要法務協助審合約" in trend_block
    assert "跟客戶開了兩次會" not in trend_block
    assert "內部對齊了規格" not in trend_block


def test_沒有任何報告時也能產生網頁不會炸():
    html = render.render_site([])
    assert "尚無報告" in html


def test_報告與網頁的儲存路徑():
    assert render.report_path("2026-08-14") == "data/published/2026-08-14/report.md"
    # 網站是固定位置，不隨期別改變 —— Cloudflare Pages 才盯得住
    assert render.site_path() == "site/index.html"


def test_內容中的_HTML_標籤不會被當成標記執行():
    danger = render.Report(label="2026-08-14", markdown="## 本期重點\n\n<script>x</script>\n")
    html = render.render_site([danger])
    assert "<script>x</script>" not in html


def test_label_中的_HTML_標籤不會被當成標記執行():
    # label 跟 markdown 是兩條各自獨立進入模板的路徑，這裡驗證 label 也有跳脫，
    # 不能只靠呼叫端（例如目前固定回傳 ISO 日期字串的 periods.period_label()）剛好安全。
    danger = render.Report(label="<img src=x onerror=alert(1)>", markdown=SAMPLE)
    html = render.render_site([danger])
    assert "<img src=x onerror=alert(1)>" not in html


def test_趨勢表格的內容格帶有欄位名稱標籤():
    reports = [render.Report(label="2026-08-14", markdown=SAMPLE)]
    html = render.render_site(reports)
    trend_block = _trend_block(html)
    assert 'data-label="本期重點"' in trend_block
    assert 'data-label="問題與需要協助"' in trend_block


def test_趨勢表格的期別格不帶標籤():
    reports = [render.Report(label="2026-08-14", markdown=SAMPLE)]
    html = render.render_site(reports)
    trend_block = _trend_block(html)
    assert '<td>2026-08-14</td>' in trend_block


def test_窄螢幕樣式含卡片堆疊規則():
    html = render.render_site([render.Report(label="2026-08-14", markdown=SAMPLE)])
    assert "@media (max-width: 40rem)" in html
    media_start = html.index("@media (max-width: 40rem)")
    media_end = html.index("</style>", media_start)
    media_block = html[media_start:media_end]
    assert "thead { display: none; }" in media_block
    assert "td[data-label]::before" in media_block


def test_網站固定產生在同一個位置():
    assert render.SITE_PATH == "site/index.html"


def test_每期報告原稿仍各自存檔():
    assert render.report_path("2026-08-14") == "data/published/2026-08-14/report.md"
