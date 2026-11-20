from __future__ import annotations


import duckdb
import pandas as pd
import streamlit as st

from data_access import begin_mock_tracking, download_gold_path, load_gold_table, load_log_table, render_mock_banner

st.set_page_config(page_title="WorldCup Pulse DataOps", page_icon="⚙️", layout="wide", initial_sidebar_state="expanded")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
:root { --bg:#020617; --panel:#08111F; --border:#1E3A5F; --indigo:#3454FF; --cyan:#00D4FF; --neon:#00F5A0; --pink:#FF3CAC; --red:#7F1D1D; --amber:#FFD166; --text:#F8FBFF; --muted:#9DB4C8; }
html, body, [class*="css"] { font-family: Inter, Segoe UI, sans-serif; }
.stApp { background: radial-gradient(circle at top left, rgba(52,84,255,.18), transparent 30%), radial-gradient(circle at top right, rgba(0,245,160,.10), transparent 30%), var(--bg); color: var(--text); }
#MainMenu, header, footer { visibility:hidden; height:0; }
.block-container { padding-top: 1rem; padding-bottom: 2rem; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #030712 0%, #08111F 100%); border-right: 1px solid var(--border); }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 8px !important; border: 1px solid #222b35 !important; background: linear-gradient(180deg, rgba(8,17,31,.95), rgba(2,6,23,.95)); box-shadow: 0 0 26px rgba(0,212,255,.08); }
.hero { border:1px solid var(--border); border-radius:12px; padding:20px 22px; background:linear-gradient(135deg,rgba(52,84,255,.22),rgba(0,212,255,.08),rgba(0,245,160,.08)); margin-bottom:16px; }
.hero h1 { margin:0; font-size:2.1rem; letter-spacing:-.04em; }
.hero p { color:var(--muted); margin:.4rem 0 0 0; }
.kcard { border:1px solid #222b35; border-radius:8px; padding:14px 16px; background:linear-gradient(180deg,rgba(8,17,31,.95),rgba(3,7,18,.95)); box-shadow: 0 0 24px rgba(0,212,255,.08); min-height:96px; }
.klabel { color:var(--muted); font-size:.78rem; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }
.kvalue { color:var(--text); font-size:1.45rem; font-weight:800; margin-top:8px; }
.badge { display:inline-block; padding:4px 9px; border-radius:999px; font-weight:800; font-size:.78rem; border:1px solid; }
.badge-success { color:#052e16; background:var(--neon); border-color:var(--neon); box-shadow:0 0 14px rgba(0,245,160,.35); }
.badge-fail { color:#fff; background:var(--red); border-color:#ef4444; }
.badge-warn { color:#111827; background:var(--amber); border-color:var(--amber); }
.sqlbox { border:1px solid var(--border); border-radius:10px; padding:12px; background:#030712; color:#00F5A0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.sidebar-logo { border:1px solid var(--border); border-radius:10px; padding:14px; background:rgba(2,6,23,.7); text-align:center; margin-top:18px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

GOLD_TABLES = [
    "kpi_summary.parquet",
    "goals_by_matchday.parquet",
    "goals_by_minute_bucket.parquet",
    "host_cities.parquet",
    "team_radar_stats.parquet",
    "team_key_metrics.parquet",
    "top_players.parquet",
    "team_table.parquet",
    "matches.parquet",
    "group_standings.parquet",
    "match_events.parquet",
]


def status_badge(status: str) -> str:
    s = str(status or "").lower()
    if "success" in s:
        return '<span class="badge badge-success">Success</span>'
    if "fail" in s:
        return '<span class="badge badge-fail">Fail</span>'
    return f'<span class="badge badge-warn">{status}</span>'


def next_run_text() -> str:
    # The scheduled refresh is disabled (tournament over); runs are manual or token-authenticated Worker dispatches.
    return "Manual only"


def card(label: str, value: str, icon: str):
    st.markdown(f'<div class="kcard"><div class="klabel">{icon} {label}</div><div class="kvalue">{value}</div></div>', unsafe_allow_html=True)


def heartbeat():
    runs = load_log_table("pipeline_runs.csv")
    if "finished_at" in runs.columns:
        runs = runs.sort_values("finished_at", ascending=False)
    latest = runs.iloc[0].to_dict() if not runs.empty else {}
    c1, c2, c3, c4 = st.columns(4)
    with c1: card("Latest Status", str(latest.get("status", "Unknown")), "🫀")
    with c2: card("Last Sync from HF Dataset", str(latest.get("finished_at", "N/A"))[:19], "🔄")
    with c3: card("Next Scheduled Run", next_run_text(), "⏱️")
    with c4: card("Gold Rows", str(latest.get("rows_gold", "N/A")), "🏅")
    st.markdown("#### Pipeline Heartbeat")
    view = runs.head(15).copy()
    if not view.empty and "status" in view.columns:
        view["status_badge"] = view["status"].map(status_badge)
        html = view[[c for c in ["run_id","started_at","finished_at","status_badge","rows_bronze","rows_silver","rows_gold","error_message"] if c in view.columns]].to_html(escape=False, index=False)
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.info("No pipeline runs available yet.")


def quality_tabs():
    q = load_log_table("quality_checks.csv")
    tabs = st.tabs(["Overview", "Bronze", "Silver", "Gold"])
    layers = [None, "Bronze", "Silver", "Gold"]
    for tab, layer in zip(tabs, layers):
        with tab:
            df = q.copy() if layer is None else q[q["layer"].astype(str).str.lower().eq(layer.lower())].copy()
            if df.empty:
                st.warning("No checks found for this layer.")
                continue
            status = df["status"].astype(str).str.lower()
            pass_count = int(status.eq("pass").sum())
            warn_count = int(status.eq("warn").sum())
            fail_count = int(len(df) - pass_count - warn_count)
            c1, c2, c3 = st.columns(3)
            with c1: card("Checks Passed", str(pass_count), "✅")
            with c2: card("Warnings", str(warn_count), "⚠️")
            with c3: card("Checks Failed", str(fail_count), "🚨")
            for _, row in df.iterrows():
                row_status = str(row.get("status", "")).lower()
                prefix = "⚠️ " if row_status == "warn" else ""
                with st.status(f"{prefix}{row.get('layer','')} · {row.get('table','')} · {row.get('check_name','')}", state="error" if row_status == "fail" else "complete"):
                    st.write(row.get("message", ""))


def duckdb_console():
    st.markdown("#### DuckDB Console")
    table = st.selectbox("Gold table", GOLD_TABLES)
    path = download_gold_path(table)
    query = f"SELECT * FROM '{path}' LIMIT 10" if path else f"SELECT * FROM mock_{table.replace('.parquet','')} LIMIT 10"
    st.markdown(f'<div class="sqlbox">{query}</div>', unsafe_allow_html=True)
    if path:
        try:
            df = duckdb.sql(query).df()
        except Exception as exc:
            st.error(f"DuckDB read failed: {exc}")
            df = load_gold_table(table).head(10)
    else:
        df = load_gold_table(table).head(10)
    search = st.text_input("Smart search", placeholder="Type to filter rows...")
    if search and not df.empty:
        mask = df.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        df = df[mask]
    st.dataframe(df, use_container_width=True, hide_index=True)


st.sidebar.markdown("### WorldCup Pulse")
st.sidebar.radio("Navigation", ["⚙️ Data Ops Monitor"], label_visibility="collapsed")
st.sidebar.markdown('<div class="sidebar-logo"><div style="font-size:2.2rem">🛠️⚽</div><b>DataOps Console</b><br><span style="color:#9DB4C8;font-size:.8rem">Pipeline · Quality · Warehouse</span></div>', unsafe_allow_html=True)
st.sidebar.caption("Manual / Worker dispatch → GitHub Actions → HF Dataset")

st.markdown('<div class="hero"><h1>⚙️ WorldCup Pulse Data Ops Monitor</h1><p>Operational view for the ETL run log, lakehouse quality checks, and DuckDB gold marts.</p></div>', unsafe_allow_html=True)
mock_banner = begin_mock_tracking()
try:
    heartbeat()
    st.markdown("---")
    st.markdown("### Data Quality Tabs")
    quality_tabs()
    st.markdown("---")
    duckdb_console()
finally:
    render_mock_banner(mock_banner)
