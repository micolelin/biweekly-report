"""雙週報告工作台。

本機啟動方式：
    cd /Users/admin/git/micolelin/biweekly-report
    set -a && source /Users/admin/Documents/m-agent/.env && set +a
    python3 -m streamlit run app.py

部署在 Streamlit Community Cloud 時，憑證改由 st.secrets 提供，
由 secrets_bridge 灌進環境變數，其餘程式碼不需要區分執行環境。

資料一律存在 GitHub micolelin/biweekly-report 的 data/ 底下，本機不留任何副本。
"""
from datetime import datetime

import streamlit as st

from biweekly.secrets_bridge import load_secrets_into_env

# 必須在任何會讀取環境變數的程式碼之前執行
load_secrets_into_env()

from biweekly import (  # noqa: E402
    config as config_mod,
    entries as entries_mod,
    github_store,
    notify,
    periods,
    render,
    summarize as summarize_mod,
)

st.set_page_config(page_title="Biweekly Report Studio", page_icon="📝", layout="wide")


@st.cache_resource
def get_store():
    return github_store.from_env()


def load_settings(store):
    return config_mod.load_config(store)


def show_error(context: str, exc: Exception) -> None:
    """把錯誤明確顯示出來，絕不靜默吞掉。"""
    st.error(f"{context}: {exc}")


try:
    store = get_store()
    settings = load_settings(store)
except Exception as exc:  # noqa: BLE001
    st.error(f"Cannot reach GitHub: {exc}")
    st.info(
        "All data lives in the cloud, so this app cannot run offline. "
        "Check your connection and that GITHUB_TOKEN is available."
    )
    st.stop()

anchor = config_mod.anchor_date(settings)
today = periods.taipei_today()
period_start, period_end = periods.period_range(anchor, today)
period_label = periods.period_label(period_end)

st.title("📝 Biweekly Report Studio")
st.caption(f"Current period: {period_start.isoformat()} – {period_end.isoformat()}")

tab_note, tab_list, tab_report, tab_history = st.tabs(
    ["Quick Note", "This Period", "Generate Report", "History"]
)


# --- 隨手記 ---------------------------------------------------------------
with tab_note:
    st.subheader("Add a note")

    # 顯示上一輪儲存成功的訊息（rerun 會沖掉當下的 st.success，所以用 session_state 帶過來）
    flash = st.session_state.pop("note_flash", None)
    if flash:
        st.success(flash)

    # 序號一變，下面所有 widget 的 key 就變，Streamlit 會建立全新的空白元件，
    # 避免在 widget 已實例化後直接改 session_state（Streamlit 明文禁止，會拋例外）
    nonce = st.session_state.get("note_nonce", 0)

    category = st.selectbox(
        "Category", settings["categories"], key=f"note_category_{nonce}"
    )
    source = st.text_input("Source", value="Me", key=f"note_source_{nonce}")
    body = st.text_area("Note", height=180, key=f"note_body_{nonce}")
    uploads = st.file_uploader(
        "Attachments (multiple allowed, 100 MB per file)",
        accept_multiple_files=True,
        key=f"note_uploads_{nonce}",
    )
    include = st.checkbox("Include in report", value=True, key=f"note_include_{nonce}")

    if st.button("Save", type="primary", key=f"note_save_{nonce}"):
        if not body.strip():
            st.warning("The note is empty — nothing was saved.")
        else:
            timestamp = datetime.now(periods.TAIPEI)
            files = {}
            attachment_paths = []
            for uploaded in uploads or []:
                path = entries_mod.attachment_path(timestamp, uploaded.name)
                files[path] = uploaded.getvalue()
                attachment_paths.append(path)

            entry = entries_mod.Entry(
                timestamp=timestamp,
                category=category,
                body=body,
                source=source or "Me",
                include_in_report=include,
                attachments=attachment_paths,
            )
            files[entries_mod.entry_path(entry)] = entries_mod.to_markdown(
                entry
            ).encode("utf-8")

            try:
                store.commit_files(files, f"note ({category}): {body.strip()[:30]}")
            except github_store.FileTooLargeError as exc:
                # 內容留在輸入框，使用者不會白打；nonce 不動，widget 保持原樣
                show_error("Attachment too large — nothing was saved", exc)
            except Exception as exc:  # noqa: BLE001
                show_error("Save failed — your text is still in the box above", exc)
            else:
                # 成功：訊息存進 session_state、序號 +1，重跑一次讓 widget 全部換新
                st.session_state["note_flash"] = (
                    f"Saved with {len(attachment_paths)} attachment(s)."
                )
                st.session_state["note_nonce"] = nonce + 1
                st.rerun()


# --- 本期清單 -------------------------------------------------------------
with tab_list:
    st.subheader("Entries this period")

    if st.button("Reload", key="list_reload"):
        st.session_state.pop("period_entries", None)

    if "period_entries" not in st.session_state:
        try:
            st.session_state["period_entries"] = summarize_mod.collect_period_entries(
                store, period_start, period_end
            )
        except Exception as exc:  # noqa: BLE001
            show_error("Could not load entries", exc)
            st.session_state["period_entries"] = []

    period_entries = st.session_state["period_entries"]
    st.caption(f"{len(period_entries)} entries (excluding those marked not for report)")

    for entry in period_entries:
        with st.expander(
            f"{entry.timestamp.strftime('%m-%d %H:%M')} · {entry.category} · {entry.body[:30]}"
        ):
            st.write(entry.body)
            st.caption(f"Source: {entry.source}")
            for attachment in entry.attachments:
                st.caption(f"Attachment: {attachment}")
            if st.button("Delete this entry", key=f"delete_{entries_mod.entry_path(entry)}"):
                try:
                    # 連同附件一起刪，否則附件會變成沒人指向的孤兒檔案
                    store.delete_files(
                        entries_mod.all_paths(entry),
                        f"delete note ({entry.category})",
                    )
                except Exception as exc:  # noqa: BLE001
                    show_error("Delete failed", exc)
                else:
                    st.session_state.pop("period_entries", None)
                    removed = len(entry.attachments)
                    st.success(
                        f"Deleted the note and {removed} attachment(s). Press Reload."
                        if removed
                        else "Deleted. Press Reload."
                    )


# --- 產生報告 -------------------------------------------------------------
with tab_report:
    st.subheader(f"Generate the report for {period_label}")

    provider_options = list(summarize_mod.PROVIDER_MODELS.keys())
    configured_provider = settings.get(
        "summarize_provider", summarize_mod.DEFAULT_PROVIDER
    )
    if configured_provider not in provider_options:
        configured_provider = summarize_mod.DEFAULT_PROVIDER
    provider = st.selectbox(
        "Summarizer",
        provider_options,
        index=provider_options.index(configured_provider),
        key="report_provider",
    )

    if st.button("Generate draft", key="report_generate"):
        try:
            with st.spinner(f"Summarising with {provider}…"):
                items = summarize_mod.collect_period_entries(
                    store, period_start, period_end
                )
                text = summarize_mod.summarize(
                    items, period_start, period_end, provider=provider
                )
        except Exception as exc:  # noqa: BLE001
            show_error(
                "Summarising failed — you can still write the draft manually below", exc
            )
        else:
            # 必須直接寫進 text_area 自己的 key。寫進別的鍵再靠 value= 帶入是沒用的：
            # widget 一旦渲染過，Streamlit 就優先採用它記住的值而忽略 value=，
            # 畫面會完全沒有反應。此處 widget 尚未在本次執行中被實例化，賦值合法。
            st.session_state["draft_editor"] = text
            st.info(f"Draft generated from {len(items)} note(s). Review it below.")

    draft = st.text_area("Draft (edit freely)", height=420, key="draft_editor")

    if st.button("Save and publish", type="primary", key="report_publish"):
        if not draft.strip():
            st.warning("The draft is empty — nothing was published.")
        else:
            try:
                store.commit_files(
                    {render.report_path(period_label): draft.encode("utf-8")},
                    f"report: {period_label}",
                )
                labels = sorted(
                    set(store.list_subdirs(render.PUBLISHED_ROOT)) | {period_label},
                    reverse=True,
                )
                reports = []
                for label in labels:
                    if label == period_label:
                        reports.append(render.Report(label=label, markdown=draft))
                        continue
                    try:
                        text = store.read_file(render.report_path(label)).decode("utf-8")
                    except FileNotFoundError:
                        continue
                    reports.append(render.Report(label=label, markdown=text))

                site_html = render.render_site(reports)
                store.commit_files(
                    {render.site_path(): site_html.encode("utf-8")},
                    f"site: {period_label}",
                )
            except Exception as exc:  # noqa: BLE001
                show_error("Publish failed", exc)
                notify.notify_error(f"Biweekly report publish failed ({period_label}): {exc}")
            else:
                st.success(
                    "Saved to GitHub. Cloudflare will refresh the report page "
                    "automatically in a minute or two."
                )

                site_url = settings.get("site_url") or "(site URL not configured yet)"
                # 段落標題必須跟 SECTIONS_FOR_TREND[0] 一致，否則這裡會抓到空字串
                highlights = render.extract_section(
                    draft, render.SECTIONS_FOR_TREND[0]
                )
                st.text_area(
                    "Copy this into Outlook",
                    value=(
                        f"Hi,\n\nHere is the work report for {period_label}.\n\n"
                        f"{highlights}\n\n"
                        f"Full report: {site_url}\n"
                    ),
                    height=220,
                    key="mail_body",
                )
                manager_email = settings.get("manager_email")
                st.caption(
                    f"Recipient: {manager_email}"
                    if manager_email
                    else "Manager email not set (optional) — add it to data/config.json anytime"
                )


# --- 歷史 -----------------------------------------------------------------
with tab_history:
    st.subheader("Past periods")
    try:
        labels = sorted(store.list_subdirs(render.PUBLISHED_ROOT), reverse=True)
    except Exception as exc:  # noqa: BLE001
        show_error("Could not read past reports", exc)
        labels = []

    if not labels:
        st.info("No reports published yet.")
    for label in labels:
        with st.expander(label):
            try:
                st.markdown(
                    store.read_file(render.report_path(label)).decode("utf-8")
                )
            except Exception as exc:  # noqa: BLE001
                show_error(f"讀取 {label} 失敗", exc)
