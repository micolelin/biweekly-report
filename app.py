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

st.set_page_config(page_title="雙週報告工作台", page_icon="📝", layout="wide")


@st.cache_resource
def get_store():
    return github_store.from_env()


def load_settings(store):
    return config_mod.load_config(store)


def show_error(context: str, exc: Exception) -> None:
    """把錯誤明確顯示出來，絕不靜默吞掉。"""
    st.error(f"{context}：{exc}")


try:
    store = get_store()
    settings = load_settings(store)
except Exception as exc:  # noqa: BLE001
    st.error(f"無法連線 GitHub：{exc}")
    st.info(
        "本系統資料全部存在雲端，離線時無法使用。"
        "請確認網路連線，以及 .env 中的 GITHUB_TOKEN 已載入。"
    )
    st.stop()

anchor = config_mod.anchor_date(settings)
today = periods.taipei_today()
period_start, period_end = periods.period_range(anchor, today)
period_label = periods.period_label(period_end)

st.title("📝 雙週報告工作台")
st.caption(f"本期：{period_start.isoformat()} 至 {period_end.isoformat()}")

tab_note, tab_list, tab_report, tab_history = st.tabs(
    ["隨手記", "本期清單", "產生報告", "歷史"]
)


# --- 隨手記 ---------------------------------------------------------------
with tab_note:
    st.subheader("隨手記一筆")

    # 顯示上一輪儲存成功的訊息（rerun 會沖掉當下的 st.success，所以用 session_state 帶過來）
    flash = st.session_state.pop("note_flash", None)
    if flash:
        st.success(flash)

    # 序號一變，下面所有 widget 的 key 就變，Streamlit 會建立全新的空白元件，
    # 避免在 widget 已實例化後直接改 session_state（Streamlit 明文禁止，會拋例外）
    nonce = st.session_state.get("note_nonce", 0)

    category = st.selectbox(
        "類別", settings["categories"], key=f"note_category_{nonce}"
    )
    source = st.text_input("來源", value="自己", key=f"note_source_{nonce}")
    body = st.text_area("內容", height=180, key=f"note_body_{nonce}")
    uploads = st.file_uploader(
        "附件（可多選，單檔上限 100 MB）",
        accept_multiple_files=True,
        key=f"note_uploads_{nonce}",
    )
    include = st.checkbox("納入報告", value=True, key=f"note_include_{nonce}")

    if st.button("儲存", type="primary", key=f"note_save_{nonce}"):
        if not body.strip():
            st.warning("內容是空的，沒有儲存。")
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
                source=source or "自己",
                include_in_report=include,
                attachments=attachment_paths,
            )
            files[entries_mod.entry_path(entry)] = entries_mod.to_markdown(
                entry
            ).encode("utf-8")

            try:
                store.commit_files(files, f"記錄（{category}）：{body.strip()[:30]}")
            except github_store.FileTooLargeError as exc:
                # 內容留在輸入框，使用者不會白打；nonce 不動，widget 保持原樣
                show_error("附件太大，未儲存", exc)
            except Exception as exc:  # noqa: BLE001
                show_error("儲存失敗，內容仍保留在上方輸入框", exc)
            else:
                # 成功：訊息存進 session_state、序號 +1，重跑一次讓 widget 全部換新
                st.session_state["note_flash"] = (
                    f"已儲存，附件 {len(attachment_paths)} 個。"
                )
                st.session_state["note_nonce"] = nonce + 1
                st.rerun()


# --- 本期清單 -------------------------------------------------------------
with tab_list:
    st.subheader("本期記錄")

    if st.button("重新載入", key="list_reload"):
        st.session_state.pop("period_entries", None)

    if "period_entries" not in st.session_state:
        try:
            st.session_state["period_entries"] = summarize_mod.collect_period_entries(
                store, period_start, period_end
            )
        except Exception as exc:  # noqa: BLE001
            show_error("載入記錄失敗", exc)
            st.session_state["period_entries"] = []

    period_entries = st.session_state["period_entries"]
    st.caption(f"共 {len(period_entries)} 筆（已排除標記為不進報告的）")

    for entry in period_entries:
        with st.expander(
            f"{entry.timestamp.strftime('%m-%d %H:%M')}｜{entry.category}｜{entry.body[:30]}"
        ):
            st.write(entry.body)
            st.caption(f"來源：{entry.source}")
            for attachment in entry.attachments:
                st.caption(f"附件：{attachment}")
            if st.button("刪除這筆", key=f"delete_{entries_mod.entry_path(entry)}"):
                try:
                    store.delete_files(
                        [entries_mod.entry_path(entry)], "刪除一筆記錄"
                    )
                except Exception as exc:  # noqa: BLE001
                    show_error("刪除失敗", exc)
                else:
                    st.session_state.pop("period_entries", None)
                    st.success("已刪除，請按「重新載入」。")


# --- 產生報告 -------------------------------------------------------------
with tab_report:
    st.subheader(f"產生 {period_label} 這期的報告")

    provider_options = list(summarize_mod.PROVIDER_MODELS.keys())
    configured_provider = settings.get(
        "summarize_provider", summarize_mod.DEFAULT_PROVIDER
    )
    if configured_provider not in provider_options:
        configured_provider = summarize_mod.DEFAULT_PROVIDER
    provider = st.selectbox(
        "彙整引擎",
        provider_options,
        index=provider_options.index(configured_provider),
        key="report_provider",
    )

    if st.button("整理成草稿", key="report_generate"):
        try:
            items = summarize_mod.collect_period_entries(
                store, period_start, period_end
            )
            st.session_state["draft"] = summarize_mod.summarize(
                items, period_start, period_end, provider=provider
            )
        except Exception as exc:  # noqa: BLE001
            show_error("彙整失敗，你仍可在下方手動撰寫", exc)
            st.session_state.setdefault("draft", "")

    draft = st.text_area(
        "報告草稿（可直接編修）",
        value=st.session_state.get("draft", ""),
        height=420,
        key="draft_editor",
    )

    if st.button("儲存並發布", type="primary", key="report_publish"):
        if not draft.strip():
            st.warning("草稿是空的，沒有發布。")
        else:
            try:
                store.commit_files(
                    {render.report_path(period_label): draft.encode("utf-8")},
                    f"報告：{period_label}",
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
                    {render.site_path(period_label): site_html.encode("utf-8")},
                    f"網頁：{period_label}",
                )
            except Exception as exc:  # noqa: BLE001
                show_error("發布失敗", exc)
                notify.notify_error(f"雙週報告發布失敗（{period_label}）：{exc}")
            else:
                st.success("已存到 GitHub。接著執行 Task 8 的部署指令推上 Cloudflare。")

                site_url = settings.get("site_url") or "（尚未設定網址）"
                highlights = render.extract_section(draft, "本期重點")
                st.text_area(
                    "複製這段貼進 Outlook 寄給主管",
                    value=(
                        f"主管好，{period_label} 這期的工作報告如下：\n\n"
                        f"{highlights}\n\n"
                        f"完整內容請看：{site_url}\n"
                    ),
                    height=220,
                    key="mail_body",
                )
                manager_email = settings.get("manager_email")
                st.caption(
                    f"收件者：{manager_email}"
                    if manager_email
                    else "尚未設定主管 email（選填），可日後填入 data/config.json"
                )


# --- 歷史 -----------------------------------------------------------------
with tab_history:
    st.subheader("歷史各期")
    try:
        labels = sorted(store.list_subdirs(render.PUBLISHED_ROOT), reverse=True)
    except Exception as exc:  # noqa: BLE001
        show_error("讀取歷史失敗", exc)
        labels = []

    if not labels:
        st.info("尚無已發布的報告。")
    for label in labels:
        with st.expander(label):
            try:
                st.markdown(
                    store.read_file(render.report_path(label)).decode("utf-8")
                )
            except Exception as exc:  # noqa: BLE001
                show_error(f"讀取 {label} 失敗", exc)
