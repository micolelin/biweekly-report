"""產生給主管看的靜態網頁。

刻意做成單一 HTML 檔、不引用任何外部資源（字型、CSS、JS 一律內嵌），
因為主管兩週才點一次，開啟速度是這個系統成敗的關鍵。
"""
import html as html_lib
import re
from dataclasses import dataclass

import markdown as markdown_lib
from jinja2 import Template

PUBLISHED_ROOT = "data/published"

SECTIONS_FOR_TREND = ["本期重點", "問題與需要協助"]


@dataclass
class Report:
    label: str
    markdown: str


def extract_section(markdown_text: str, heading: str) -> str:
    """取出指定二級標題底下的內容，不含下一個標題。"""
    pattern = re.compile(
        rf"^##\s*{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown_text)
    return match.group(1).strip() if match else ""


def _to_html(markdown_text: str) -> str:
    """Markdown 轉 HTML。先跳脫 HTML 標籤，避免記錄內容被當成標記執行。"""
    return markdown_lib.markdown(
        html_lib.escape(markdown_text), extensions=["tables", "nl2br"]
    )


PAGE_TEMPLATE = Template(
    """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>雙週工作報告</title>
<style>
  :root { color-scheme: light dark; }
  body {
    margin: 0 auto; padding: 1.5rem; max-width: 52rem; line-height: 1.75;
    font-family: -apple-system, "Helvetica Neue", "PingFang TC",
                 "Microsoft JhengHei", sans-serif;
  }
  h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
  h2 { font-size: 1.15rem; margin-top: 2rem; }
  nav { display: flex; gap: 0.5rem; margin: 1.25rem 0 2rem; flex-wrap: wrap; }
  nav a {
    padding: 0.4rem 0.9rem; border: 1px solid currentColor; border-radius: 999px;
    text-decoration: none; color: inherit; font-size: 0.9rem;
  }
  section { display: none; }
  section:target { display: block; }
  section#current:not(:target) { display: block; }
  body:has(section#history:target) section#current:not(:target),
  body:has(section#trend:target) section#current:not(:target) { display: none; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid currentColor; padding: 0.5rem; text-align: left;
           vertical-align: top; }
  .period { margin-bottom: 2.5rem; }
  .muted { opacity: 0.7; font-size: 0.9rem; }
  @media (max-width: 40rem) {
    body { padding: 1rem; }

    /* 窄螢幕不用表格：一期一張卡片，文字取得整個寬度 */
    table, tbody, tr, td { display: block; width: 100%; }
    thead { display: none; }
    tr {
      border: 1px solid currentColor;
      border-radius: 0.5rem;
      padding: 0.75rem;
      margin-bottom: 1.25rem;
    }
    td { border: none; padding: 0 0 0.75rem; }
    td:last-child { padding-bottom: 0; }
    td:first-child {
      font-weight: 600;
      font-size: 1.05rem;
      border-bottom: 1px solid currentColor;
      padding-bottom: 0.5rem;
      margin-bottom: 0.75rem;
    }
    td[data-label]::before {
      content: attr(data-label);
      display: block;
      font-weight: 600;
      opacity: 0.7;
      font-size: 0.85rem;
      margin-bottom: 0.25rem;
    }
  }
</style>
</head>
<body>
<h1>雙週工作報告</h1>
{% if reports %}
<p class="muted">最新一期：{{ reports[0].label }}</p>
{% endif %}

<nav>
  <a href="#current">本期</a>
  <a href="#history">歷史</a>
  <a href="#trend">趨勢對照</a>
</nav>

<section id="current">
{% if reports %}
{{ reports[0].html }}
{% else %}
<p>尚無報告。</p>
{% endif %}
</section>

<section id="history">
{% if reports %}
{% for report in reports %}
<div class="period">
  <h2>{{ report.label }}</h2>
  {{ report.html }}
</div>
{% endfor %}
{% else %}
<p>尚無報告。</p>
{% endif %}
</section>

<section id="trend">
{% if trend_rows %}
<p class="muted">最近數期的重點與待解問題並列，方便看出哪些問題延續。</p>
<table>
  <thead>
    <tr><th>期別</th>{% for name in section_names %}<th>{{ name }}</th>{% endfor %}</tr>
  </thead>
  <tbody>
  {% for row in trend_rows %}
    <tr>
      <td>{{ row.label }}</td>
      {% for cell in row.cells %}<td data-label="{{ section_names[loop.index0] }}">{{ cell }}</td>{% endfor %}
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>尚無報告。</p>
{% endif %}
</section>
</body>
</html>
"""
)


def render_site(reports: list[Report]) -> str:
    """產生完整網頁。reports 需由新到舊排序。

    label 與 markdown 是兩條各自獨立進入未跳脫模板（autoescape=False）的路徑，
    因此 label 這裡也要跳脫，不能只靠呼叫端（例如 periods.period_label()
    目前固定回傳 ISO 日期格式）剛好安全；否則日後若有呼叫端改用自由文字當
    label，就會重新打開這個注入路徑。
    """
    prepared = [
        {"label": html_lib.escape(report.label), "html": _to_html(report.markdown)}
        for report in reports
    ]
    trend_rows = [
        {
            "label": html_lib.escape(report.label),
            "cells": [
                _to_html(extract_section(report.markdown, name))
                for name in SECTIONS_FOR_TREND
            ],
        }
        for report in reports
    ]
    return PAGE_TEMPLATE.render(
        reports=prepared,
        trend_rows=trend_rows,
        section_names=SECTIONS_FOR_TREND,
    )


def report_path(label: str) -> str:
    return f"{PUBLISHED_ROOT}/{label}/report.md"


def site_path(label: str) -> str:
    return f"{PUBLISHED_ROOT}/{label}/index.html"
