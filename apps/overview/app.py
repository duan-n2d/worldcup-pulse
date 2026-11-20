from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

from data_access import begin_mock_tracking, load_gold_table, render_mock_banner

st.set_page_config(page_title="WorldCup Pulse Overview", page_icon="⚽", layout="wide", initial_sidebar_state="expanded")

# ---------------------------------------------------------------------------
# DATA DEPENDENCIES
#
# Tables already used by the original dashboard (no ETL change needed):
#   kpi_summary.parquet, goals_by_matchday.parquet, goals_by_minute_bucket.parquet,
#   host_cities.parquet, team_key_metrics.parquet, team_radar_stats.parquet,
#   top_players.parquet
#
# NEW tables this revision can use if present (every page degrades gracefully
# with an in-app "waiting on ETL" notice + documented schema if a table is
# missing, so nothing here can crash the app):
#
#   matches.parquet
#       match_id, matchday, stage, group, match_date, kickoff_local, venue, city,
#       home_team, home_flag, away_team, away_flag, home_score, away_score,
#       home_xg, away_xg, attendance, status ("completed"|"live"|"scheduled")
#       (xg/attendance/date are null when the source API does not provide them)
#
#   group_standings.parquet
#       group, team, flag, played, won, drawn, lost, goals_for, goals_against,
#       goal_diff, points, qualification_status ("qualified"|"in_contention"|"eliminated")
#
#   match_events.parquet  (powers the Match Detail timeline, shot map, and the
#       Tournament Patterns tab)
#       match_id, minute, half (1|2|3 for ET), event_type
#       ("goal"|"penalty_goal"|"var_goal"|"own_goal"|"yellow_card"|"red_card"),
#       team, player, assist_player, shot_x, shot_y (0-100 pitch coords, goals only)
#       NOTE: "team" on a goal event = the team CREDITED with the goal
#       (an own goal is credited to the attacking/benefiting side).
#
# The pipeline never estimates stats the source API does not carry. xG, shots,
# possession, pass accuracy, cards, set-piece goals, assists, positions, shot
# coordinates and attendance are null unless the API reports them, and every
# view below hides or labels a stat that has no values. Lineups, substitutions,
# goalkeeper stats and per-player ratings / physical stats are not produced.
#
# OPTIONAL columns on EXISTING tables (missing or null values show "N/A"):
#   kpi_summary.parquet      + matches_remaining, total_yellow_cards, total_red_cards,
#                              penalties_awarded, var_goals
#   team_key_metrics.parquet + goals_against, clean_sheets, setpiece_goals
#   top_players.parquet      + position, assists
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
:root { --bg:#020617; --panel:#08111F; --border:#1E3A5F; --indigo:#3454FF; --cyan:#00D4FF; --neon:#00F5A0; --pink:#FF3CAC; --amber:#FFD166; --text:#F8FBFF; --muted:#9DB4C8; }
html, body, [class*="css"] { font-family: Inter, Segoe UI, sans-serif; }
.stApp { background: radial-gradient(circle at top left, rgba(52,84,255,.18), transparent 30%), radial-gradient(circle at top right, rgba(0,245,160,.12), transparent 30%), var(--bg); color: var(--text); }
#MainMenu, header, footer { visibility:hidden; height:0; }
.block-container { padding-top: 1rem; padding-bottom: 2rem; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #030712 0%, #08111F 100%); border-right: 1px solid var(--border); }
section[data-testid="stSidebar"] * { color: var(--text); }
div[data-testid="stMetric"], div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 8px !important; border: 1px solid #222b35 !important; background: linear-gradient(180deg, rgba(8,17,31,.92), rgba(2,6,23,.92)); box-shadow: 0 0 28px rgba(0,212,255,.08); }
.card { border:1px solid #222b35; border-radius:8px; padding:14px 16px; background:linear-gradient(180deg,rgba(8,17,31,.95),rgba(3,7,18,.95)); box-shadow: 0 0 24px rgba(0,212,255,.08); min-height:100px; }
.card .label { color:var(--muted); font-size:.78rem; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }
.card .value { color:var(--text); font-size:1.45rem; font-weight:800; margin-top:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.card .sub { color:var(--cyan); font-size:.76rem; margin-top:6px; }
.hero { border:1px solid var(--border); border-radius:12px; padding:20px 22px; background:linear-gradient(135deg,rgba(52,84,255,.22),rgba(0,212,255,.08),rgba(0,245,160,.08)); margin-bottom:16px; }
.hero h1 { margin:0; font-size:2.1rem; letter-spacing:-.04em; }
.hero p { color:var(--muted); margin:.4rem 0 0 0; }
.sidebar-logo { border:1px solid var(--border); border-radius:10px; padding:14px; background:rgba(2,6,23,.7); text-align:center; margin-top:18px; }
.ghost { border:1px solid var(--cyan); color:var(--cyan); border-radius:8px; padding:8px 10px; background:rgba(0,212,255,.06); text-align:center; font-weight:700; box-shadow:0 0 18px rgba(0,212,255,.14); margin-bottom:10px; }
.progress-track { width:100%; height:8px; background:#111827; border-radius:99px; border:1px solid #223047; overflow:hidden; margin-top:7px; }
.progress-fill { height:100%; background:linear-gradient(90deg,var(--indigo),var(--cyan),var(--neon)); border-radius:99px; box-shadow:0 0 12px rgba(0,245,160,.45); }
.metric-small { font-size:1.4rem; font-weight:800; color:var(--text); }
.metric-name { font-size:.8rem; color:var(--muted); font-weight:700; }
.pill { display:inline-block; padding:2px 9px; border-radius:99px; font-size:.7rem; font-weight:800; letter-spacing:.03em; }
.pill-w { background:rgba(0,245,160,.18); color:var(--neon); border:1px solid rgba(0,245,160,.4); }
.pill-d { background:rgba(255,209,102,.18); color:var(--amber); border:1px solid rgba(255,209,102,.4); }
.pill-l { background:rgba(255,60,172,.18); color:var(--pink); border:1px solid rgba(255,60,172,.4); }
.pill-live { background:rgba(255,60,172,.22); color:var(--pink); border:1px solid var(--pink); animation:pulse 1.6s infinite; }
@keyframes pulse { 0%{opacity:1} 50%{opacity:.5} 100%{opacity:1} }
.insight-card { border-left:3px solid var(--cyan); padding:10px 14px; background:rgba(0,212,255,.05); border-radius:0 8px 8px 0; margin-bottom:8px; min-height:64px; }
.insight-card b { color:var(--cyan); }
.score-card { border:1px solid #222b35; border-radius:8px; padding:12px 16px; background:linear-gradient(180deg,rgba(8,17,31,.95),rgba(3,7,18,.95)); margin-bottom:8px; }
.score-card .vs { display:flex; justify-content:space-between; align-items:center; gap:10px; }
.score-card .team { font-weight:700; font-size:.92rem; flex:1; }
.score-card .team.away { text-align:right; }
.score-card .score { font-size:1.5rem; font-weight:800; color:var(--neon); white-space:nowrap; }
.meta-row { color:var(--muted); font-size:.74rem; margin-top:8px; }
.table-wrap { border:1px solid #222b35; border-radius:8px; overflow:hidden; margin-bottom:10px; }
.wc-table { width:100%; border-collapse:collapse; font-size:.82rem; }
.wc-table th { text-align:left; color:var(--muted); font-weight:700; padding:7px 10px; background:rgba(255,255,255,.02); }
.wc-table td { padding:7px 10px; border-top:1px solid #1b2536; }
.wc-table tr.qzone td { background:rgba(0,245,160,.07); }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

PLOTLY_TEMPLATE = "plotly_dark"
NEON = "#00F5A0"
CYAN = "#00D4FF"
INDIGO = "#3454FF"
PINK = "#FF3CAC"
AMBER = "#FFD166"
PANEL = "#08111F"
TEXT = "#F8FBFF"

# Reference points only — public record, not pulled from the lakehouse.
# Source: FIFA / Statista (Transfermarkt) goals-per-match by edition.
HISTORICAL_GOALS_PER_MATCH = {"2014": 2.67, "2018": 2.64, "2022": 2.69}


# ---------------------------------------------------------------------------
# Data + small UI helpers
# ---------------------------------------------------------------------------

def safe_load(table: str) -> tuple[pd.DataFrame, bool]:
    """Load a gold table without ever crashing a page if it isn't there yet."""
    try:
        df = load_gold_table(table)
        return df, (df is not None and not df.empty)
    except Exception:
        return pd.DataFrame(), False


def trigger_etl() -> tuple[bool, str]:
    repo = os.environ.get("GITHUB_REPO", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        return False, "Missing GITHUB_REPO or GITHUB_TOKEN Space secret."
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/dispatches",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "worldcup-pulse-space"},
            json={"event_type": "run-etl", "client_payload": {"source": "space_button"}},
            timeout=20,
        )
        return r.ok, f"GitHub dispatch status={r.status_code}"
    except Exception as exc:
        return False, str(exc)


def hero(title: str, subtitle: str):
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def fig_layout(fig):
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(8,17,31,.55)",
        font_color=TEXT,
        margin=dict(l=10, r=10, t=45, b=10),
        legend=dict(orientation="h", y=1.05),
    )
    return fig


def card(label: str, value: str, icon: str, sub: str = "live gold mart"):
    st.markdown(f'<div class="card"><div class="label">{icon} {label}</div><div class="value">{value}</div><div class="sub">{sub}</div></div>', unsafe_allow_html=True)


def progress(label: str, value: float, max_value: float = 100, suffix: str = ""):
    pct = max(0, min(100, value / max_value * 100 if max_value else 0))
    st.markdown(f'<div class="metric-name">{label}</div><div class="metric-small">{value}{suffix}</div><div class="progress-track"><div class="progress-fill" style="width:{pct}%"></div></div>', unsafe_allow_html=True)


def insight(title: str, body: str):
    st.markdown(f'<div class="insight-card"><b>{title}</b><br>{body}</div>', unsafe_allow_html=True)


def unavailable_notice(what: str):
    st.markdown(
        f'<div class="insight-card">ℹ️ <b>Not available</b> — {what} is not provided by the source API, '
        f'so it is not shown (WorldCup Pulse does not estimate missing stats).</div>',
        unsafe_allow_html=True,
    )


def has_values(df: pd.DataFrame, *cols: str) -> bool:
    """True when every column exists and has at least one non-null value."""
    return df is not None and not df.empty and all(c in df.columns and df[c].notna().any() for c in cols)


def fmt(value, suffix: str = "") -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "N/A"
    return f"{value}{suffix}"


def progress_or_na(label: str, value, max_value: float, suffix: str = "", digits: int = 1):
    if value is None or pd.isna(value):
        st.markdown(f'<div class="metric-name">{label}</div><div class="metric-small">N/A</div><div class="sub" style="color:#9DB4C8;font-size:.72rem;">not in source API</div>', unsafe_allow_html=True)
        return
    progress(label, round(float(value), digits), max_value, suffix)


def missing_data_notice(table: str, what_it_unlocks: str = ""):
    st.markdown(
        f'<div class="insight-card">⏳ <b>Waiting on data</b> — '
        f'<code>{table}</code> hasn\'t landed in the gold layer yet. {what_it_unlocks}</div>',
        unsafe_allow_html=True,
    )


def result_letter_pill(letter: str) -> str:
    cls = {"W": "pill-w", "D": "pill-d", "L": "pill-l"}.get(letter, "pill-d")
    return f'<span class="pill {cls}">{letter}</span>'


def status_pill(status: str) -> str:
    s = (status or "").lower()
    if s == "live":
        return '<span class="pill pill-live">● LIVE</span>'
    if s == "completed":
        return '<span class="pill pill-w">FT</span>'
    return '<span class="pill pill-d">UPCOMING</span>'


def render_match_card(row: pd.Series):
    home_flag = row.get("home_flag", "") or ""
    away_flag = row.get("away_flag", "") or ""
    hs = row.get("home_score", None)
    as_ = row.get("away_score", None)
    score = f"{int(hs)} — {int(as_)}" if pd.notna(hs) and pd.notna(as_) else "vs"
    meta_bits = [str(row.get(k)) for k in ("venue", "city", "match_date") if pd.notna(row.get(k)) and row.get(k) not in ("", None)]
    meta = " · ".join(meta_bits)
    st.markdown(
        f'''<div class="score-card">
            <div class="vs">
                <div class="team">{home_flag} {row.get("home_team", "")}</div>
                <div class="score">{score}</div>
                <div class="team away">{row.get("away_team", "")} {away_flag}</div>
            </div>
            <div class="meta-row">{status_pill(row.get("status", ""))} &nbsp; {meta}</div>
        </div>''',
        unsafe_allow_html=True,
    )


def render_standings_table(gdf: pd.DataFrame):
    rows_html = ""
    for _, r in gdf.iterrows():
        zone = "qzone" if str(r.get("qualification_status", "")).lower() == "qualified" else ""
        gd = int(r.get("goal_diff", 0) or 0)
        rows_html += (
            f'<tr class="{zone}">'
            f'<td>{r.get("flag", "")} {r.get("team", "")}</td>'
            f'<td>{int(r.get("played", 0) or 0)}</td>'
            f'<td>{int(r.get("won", 0) or 0)}</td>'
            f'<td>{int(r.get("drawn", 0) or 0)}</td>'
            f'<td>{int(r.get("lost", 0) or 0)}</td>'
            f'<td>{gd:+d}</td>'
            f'<td><b>{int(r.get("points", 0) or 0)}</b></td>'
            f'</tr>'
        )
    st.markdown(
        f'''<div class="table-wrap"><table class="wc-table">
            <thead><tr><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table></div>''',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def sidebar() -> str:
    st.sidebar.markdown("### WorldCup Pulse")
    pages = [
        "⚽ Overview",
        "🏟️ Match Center",
        "🏆 Group Standings",
        "📊 Team Intelligence",
        "🥇 Player Leaderboard",
        "🌆 Venues & Cities",
    ]
    page = st.sidebar.radio("Navigation", pages, label_visibility="collapsed")

    matches_df, ok = safe_load("matches.parquet")
    if ok and "status" in matches_df.columns:
        live_n = int((matches_df["status"].astype(str).str.lower() == "live").sum())
        if live_n:
            label = "match" if live_n == 1 else "matches"
            st.sidebar.markdown(f'<div class="ghost">🔴 {live_n} {label} live now</div>', unsafe_allow_html=True)

    st.sidebar.markdown('<div class="sidebar-logo"><div style="font-size:2.2rem">🏆⚽</div><b>FIFA World Cup 2026</b><br><span style="color:#9DB4C8;font-size:.8rem">Canada · Mexico · USA</span></div>', unsafe_allow_html=True)
    if st.sidebar.button("Trigger ETL Pipeline", use_container_width=True):
        ok2, msg = trigger_etl()
        st.toast(("✅ " if ok2 else "⚠️ ") + msg)
    st.sidebar.caption("Data source: HF Dataset lakehouse · cache ttl 300s")
    return page


# ---------------------------------------------------------------------------
# Page: Overview  (tournament level)
# ---------------------------------------------------------------------------

def overview():
    hero("⚽ WorldCup Pulse Lakehouse", "Football analytics from a Bronze/Silver/Gold lakehouse built by GitHub Actions, stored in a Hugging Face Dataset, and served with DuckDB and Streamlit.")

    kpi = load_gold_table("kpi_summary.parquet").iloc[0].to_dict()
    cols = st.columns(8)
    data = [
        ("Matches Played", kpi.get("matches_played", 0), "📅"),
        ("Total Goals", kpi.get("total_goals", 0), "🥅"),
        ("Avg Goals/Match", kpi.get("avg_goals_per_match", 0), "📈"),
        ("Biggest Win", kpi.get("biggest_win", "N/A"), "🔥"),
        ("Most Offensive", kpi.get("most_offensive_team", "N/A"), "⚡"),
        ("Most Defensive", kpi.get("most_defensive_team", "N/A"), "🛡️"),
        ("Avg Possession", fmt(kpi.get("avg_possession"), "%"), "🎛️"),
        ("Cards/Match", fmt(kpi.get("cards_per_match")), "🟨"),
    ]
    for c, item in zip(cols, data):
        with c:
            card(item[0], str(item[1]), item[2])

    st.markdown("#### Discipline & Set Pieces")
    d_cols = st.columns(5)
    d_data = [
        ("Matches Remaining", fmt(kpi.get("matches_remaining")), "⏳"),
        ("Yellow Cards", fmt(kpi.get("total_yellow_cards")), "🟨"),
        ("Red Cards", fmt(kpi.get("total_red_cards")), "🟥"),
        ("Penalties Awarded", fmt(kpi.get("penalties_awarded")), "🎯"),
        ("VAR Goals", fmt(kpi.get("var_goals")), "📺"),
    ]
    for c, item in zip(d_cols, d_data):
        with c:
            card(item[0], str(item[1]), item[2], sub="N/A = not in source API")

    metrics = load_gold_table("team_key_metrics.parquet")
    minute = load_gold_table("goals_by_minute_bucket.parquet")
    players, players_ok = safe_load("top_players.parquet")

    st.markdown("#### 🔍 Tournament Storylines")
    ic1, ic2, ic3, ic4 = st.columns(4)
    with ic1:
        if has_values(metrics, "goals_for", "xg", "team"):
            m2 = metrics.dropna(subset=["xg"]).copy()
            m2["finishing_delta"] = m2["goals_for"] - m2["xg"]
            top = m2.sort_values("finishing_delta", ascending=False).iloc[0]
            insight("Most Clinical", f"{top.team} have scored {top.finishing_delta:+.1f} goals above their xG — ruthless in front of net.")
    with ic2:
        if has_values(metrics, "cards", "team"):
            calm = metrics.dropna(subset=["cards"]).sort_values("cards").iloc[0]
            insight("Most Disciplined", f"{calm.team} average just {calm.cards} cards per match, the cleanest record so far.")
    with ic3:
        if not minute.empty and {"minute_bucket", "goals"}.issubset(minute.columns):
            peak = minute.sort_values("goals", ascending=False).iloc[0]
            insight("Peak Drama Window", f"The <b>{peak.minute_bucket}</b> minute bucket has the most goals ({peak.goals}) — that's when matches tend to swing.")
    with ic4:
        if players_ok and has_values(players, "goals", "player"):
            p2 = players.copy()
            if has_values(p2, "assists"):
                p2["impact"] = p2["goals"].fillna(0) + p2["assists"].fillna(0)
                star = p2.sort_values("impact", ascending=False).iloc[0]
                insight("Golden Boot Pace", f"{star.player} leads all contributors with {int(star.goals)} goals and {int(star.assists)} assists.")
            else:
                star = p2.sort_values("goals", ascending=False).iloc[0]
                insight("Golden Boot Pace", f"{star.player} leads the scoring charts with {int(star.goals)} goals.")

    st.markdown("#### Attacking vs Defensive Trend")
    avg_now = kpi.get("avg_goals_per_match")
    if avg_now is not None:
        baseline = sum(HISTORICAL_GOALS_PER_MATCH.values()) / len(HISTORICAL_GOALS_PER_MATCH)
        diff = float(avg_now) - baseline
        tilt = "more attacking than" if diff > 0.05 else ("more defensive than" if diff < -0.05 else "right in line with")
        insight("Tournament Tempo", f"At {float(avg_now):.2f} goals/match, 2026 is running {tilt} the 2014–2022 average of {baseline:.2f}.")
        combo = pd.DataFrame(
            {
                "edition": list(HISTORICAL_GOALS_PER_MATCH.keys()) + ["2026 (current)"],
                "goals_per_match": list(HISTORICAL_GOALS_PER_MATCH.values()) + [float(avg_now)],
            }
        )
        fig = px.bar(combo, x="edition", y="goals_per_match", color="edition", title="Goals per Match — 2026 vs Recent Editions", color_discrete_sequence=[INDIGO, CYAN, PINK, NEON])
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig_layout(fig), use_container_width=True)

    left, right = st.columns([1.2, 1])
    with left:
        df = load_gold_table("goals_by_matchday.parquet")
        fig = px.area(df, x="matchday", y="goals", markers=True, title="Goals Trend by Matchday")
        fig.update_traces(line=dict(color=NEON, width=3), fillcolor="rgba(0,245,160,.18)")
        fig.update_xaxes(title="Matchday", gridcolor="rgba(157,180,200,.12)")
        fig.update_yaxes(title="Goals", gridcolor="rgba(157,180,200,.12)")
        st.plotly_chart(fig_layout(fig), use_container_width=True)
    with right:
        heat = pd.DataFrame([minute.set_index("minute_bucket")["goals"].to_dict()], index=["Goals"])
        fig = go.Figure(data=go.Heatmap(z=heat.values, x=heat.columns, y=heat.index, colorscale=[[0, "#08111F"], [.5, CYAN], [1, NEON]], text=heat.values, texttemplate="%{text}", hovertemplate="%{x}: %{z} goals<extra></extra>"))
        fig.update_layout(title="Goals by Minute Bucket")
        st.plotly_chart(fig_layout(fig), use_container_width=True)

    left2, right2 = st.columns([1.25, .75])
    with left2:
        cities = load_gold_table("host_cities.parquet")
        mapped = cities.dropna(subset=["lat", "lon"]) if {"lat", "lon"}.issubset(cities.columns) else pd.DataFrame()
        if mapped.empty:
            unavailable_notice("Stadium coordinates")
        else:
            fig = px.scatter_mapbox(mapped, lat="lat", lon="lon", size="matches", color="country", hover_name="city", hover_data=["stadium", "matches"], zoom=2.1, height=430, title="Host City Map — North America")
            fig.update_layout(mapbox_style="carto-darkmatter", mapbox=dict(center={"lat": 38, "lon": -96}), margin=dict(l=0, r=0, t=45, b=0))
            st.plotly_chart(fig_layout(fig), use_container_width=True)
    with right2:
        team = metrics.sort_values("goals_for", ascending=True).tail(10)
        fig = px.bar(team, x="goals_for", y="team", orientation="h", title="Top Offensive Teams", color="goals_for", color_continuous_scale=[INDIGO, CYAN, NEON])
        st.plotly_chart(fig_layout(fig), use_container_width=True)

    st.markdown("#### Performance Analytics")
    a1, a2 = st.columns(2)
    with a1:
        if has_values(metrics, "xg"):
            m3 = metrics.dropna(subset=["xg"]).copy()
            m3["finishing_delta"] = m3["goals_for"] - m3["xg"]
            m3 = m3.sort_values("finishing_delta")
            fig = px.bar(m3, x="finishing_delta", y="team", orientation="h", title="Clinical Finishing — Goals Scored vs Expected (xG)", color="finishing_delta", color_continuous_scale=[PINK, INDIGO, NEON])
            fig.add_vline(x=0, line_dash="dot", line_color="#9DB4C8")
            st.plotly_chart(fig_layout(fig), use_container_width=True)
        else:
            unavailable_notice("Expected goals (xG)")
    with a2:
        scatter_kwargs = {}
        if has_values(metrics, "xg"):
            scatter_kwargs["size"] = metrics["xg"].fillna(0)
        if has_values(metrics, "possession_pct"):
            scatter_kwargs["color"] = "possession_pct"
        fig = px.scatter(metrics, x="fifa_rank", y="goals_for", hover_name="team", title="Giant Killers — FIFA Rank vs Goals Scored", color_continuous_scale=[INDIGO, CYAN, NEON], **scatter_kwargs)
        fig.update_xaxes(autorange="reversed", title="FIFA Rank (lower = stronger)")
        fig.update_yaxes(title="Goals For")
        st.plotly_chart(fig_layout(fig), use_container_width=True)


# ---------------------------------------------------------------------------
# Page: Match Center  (match level) — Fixtures, Match Detail, Tournament Patterns
# ---------------------------------------------------------------------------

def match_center():
    hero("🏟️ Match Center", "Live scores, fixtures, match-level breakdowns, and tournament-wide in-game patterns.")
    df, ok = safe_load("matches.parquet")
    if not ok:
        missing_data_notice("matches.parquet", "Once populated: scores, fixtures, and goal timelines.")
        return

    events_df, events_ok = safe_load("match_events.parquet")

    tab_fixtures, tab_detail, tab_patterns = st.tabs(["📋 Fixtures & Results", "🔍 Match Detail", "📐 Tournament Patterns"])

    # --- Fixtures & Results -------------------------------------------------
    with tab_fixtures:
        f1, f2, f3 = st.columns(3)
        with f1:
            stages = ["All"] + sorted(df["stage"].dropna().unique().tolist()) if "stage" in df.columns else ["All"]
            stage_sel = st.selectbox("Stage", stages, key="mc_stage")
        with f2:
            groups_ = ["All"] + sorted(df["group"].dropna().unique().tolist()) if "group" in df.columns else ["All"]
            group_sel = st.selectbox("Group", groups_, key="mc_group")
        with f3:
            status_sel = st.selectbox("Status", ["All", "completed", "live", "scheduled"], key="mc_status")

        view = df.copy()
        if stage_sel != "All" and "stage" in view.columns:
            view = view[view["stage"] == stage_sel]
        if group_sel != "All" and "group" in view.columns:
            view = view[view["group"] == group_sel]
        if status_sel != "All" and "status" in view.columns:
            view = view[view["status"].astype(str).str.lower() == status_sel]

        if {"home_score", "away_score"}.issubset(view.columns):
            completed = view[view["status"].astype(str).str.lower() == "completed"] if "status" in view.columns else view.dropna(subset=["home_score", "away_score"])
            if not completed.empty:
                completed = completed.copy()
                completed["total_goals"] = completed["home_score"] + completed["away_score"]
                ic1, ic2, ic3 = st.columns(3)
                with ic1:
                    highest = completed.sort_values("total_goals", ascending=False).iloc[0]
                    insight("Highest-Scoring Match", f"{highest.home_team} {int(highest.home_score)}–{int(highest.away_score)} {highest.away_team} — {int(highest.total_goals)} goals.")
                with ic2:
                    avg_goals = completed["total_goals"].mean()
                    insight("Avg Goals (filtered)", f"{avg_goals:.2f} goals per match across {len(completed)} completed fixtures shown.")
                with ic3:
                    if has_values(completed, "home_xg", "away_xg"):
                        completed["xg_total"] = completed["home_xg"] + completed["away_xg"]
                        completed["upset_index"] = (completed["total_goals"] - completed["xg_total"]).abs()
                        upset = completed.dropna(subset=["upset_index"]).sort_values("upset_index", ascending=False).iloc[0]
                        insight("Biggest xG Surprise", f"{upset.home_team} vs {upset.away_team} deviated most from the expected-goals script.")
                    else:
                        unavailable_notice("Expected goals (xG)")

        st.markdown("#### Fixtures & Results")
        if "match_date" in view.columns:
            view = view.sort_values("match_date")
        if view.empty:
            st.info("No matches found for this filter combination.")
        else:
            for _, row in view.iterrows():
                render_match_card(row)

    # --- Match Detail --------------------------------------------------------
    with tab_detail:
        if df.empty:
            st.info("No matches available yet.")
        else:
            opts = df.sort_values("match_date") if "match_date" in df.columns else df
            labels = [f"{r.home_team} vs {r.away_team} — {r.get('match_date', '')}" for _, r in opts.iterrows()]
            idx = st.selectbox("Pick a match", range(len(labels)), format_func=lambda i: labels[i], key="mc_detail_pick")
            match_row = opts.iloc[idx]
            render_match_card(match_row)
            match_id = match_row.get("match_id")

            if not events_ok:
                missing_data_notice("match_events.parquet", "Once populated: a minute-by-minute goal/card timeline and a shot map for this match.")
            else:
                match_events = events_df[events_df["match_id"] == match_id] if "match_id" in events_df.columns else pd.DataFrame()
                if match_events.empty:
                    st.info("No event data recorded for this match yet.")
                else:
                    st.markdown("##### Match Timeline")
                    fig = px.scatter(match_events, x="minute", y="team", color="team", symbol="event_type", hover_name="player", height=240)
                    fig.update_traces(marker=dict(size=14, line=dict(width=1, color="#020617")))
                    fig.update_xaxes(title="Minute", range=[0, max(95, match_events["minute"].max() + 5)])
                    fig.update_yaxes(title="")
                    st.plotly_chart(fig_layout(fig), use_container_width=True)

                    shots = match_events[match_events["shot_x"].notna()] if "shot_x" in match_events.columns else pd.DataFrame()
                    if not shots.empty:
                        st.markdown("##### Shot Map (goals)")
                        shot_fig = go.Figure()
                        shot_fig.add_shape(type="rect", x0=0, y0=0, x1=100, y1=100, line=dict(color="#1E3A5F"))
                        shot_fig.add_shape(type="line", x0=50, y0=0, x1=50, y1=100, line=dict(color="#1E3A5F", dash="dot"))
                        for tname, tdf in shots.groupby("team"):
                            shot_fig.add_trace(go.Scatter(x=tdf["shot_x"], y=tdf["shot_y"], mode="markers", name=tname, marker=dict(size=13, symbol="star")))
                        shot_fig.update_xaxes(visible=False, range=[0, 100])
                        shot_fig.update_yaxes(visible=False, range=[0, 100])
                        shot_fig.update_layout(height=320, title="Goal Locations")
                        st.plotly_chart(fig_layout(shot_fig), use_container_width=True)

            unavailable_notice("Lineups and substitutions")

    # --- Tournament Patterns --------------------------------------------------
    with tab_patterns:
        if not events_ok:
            missing_data_notice("match_events.parquet", "Once populated: late-goal share and lead-holding win rate across the whole tournament.")
        else:
            p1, p2 = st.columns(2)
            with p1:
                goal_events = events_df[events_df["event_type"].astype(str).str.contains("goal", case=False, na=False)] if "event_type" in events_df.columns else pd.DataFrame()
                if not goal_events.empty and {"minute", "half"}.issubset(goal_events.columns):
                    late = goal_events[((goal_events["half"] == 1) & (goal_events["minute"] >= 30)) | ((goal_events["half"] == 2) & (goal_events["minute"] >= 75))]
                    share = len(late) / len(goal_events) * 100 if len(goal_events) else 0
                    insight("Late-Goal Drama", f"{share:.0f}% of all goals are scored in the final 15 minutes of each half.")
                else:
                    missing_data_notice("match_events.parquet (minute, half columns)", "")
            with p2:
                required_events = {"match_id", "minute", "team", "event_type"}
                required_matches = {"match_id", "home_team", "away_team", "home_score", "away_score"}
                if required_events.issubset(events_df.columns) and required_matches.issubset(df.columns):
                    held, total = 0, 0
                    for _, m in df.dropna(subset=["home_score", "away_score"]).iterrows():
                        mid = m.get("match_id")
                        mev = events_df[(events_df["match_id"] == mid) & (events_df["event_type"].astype(str).str.contains("goal", case=False, na=False)) & (events_df["minute"] <= 70)]
                        if mev.empty:
                            continue
                        hg = int((mev["team"] == m["home_team"]).sum())
                        ag = int((mev["team"] == m["away_team"]).sum())
                        if hg == ag:
                            continue
                        leader = m["home_team"] if hg > ag else m["away_team"]
                        if m["home_score"] == m["away_score"]:
                            continue
                        winner = m["home_team"] if m["home_score"] > m["away_score"] else m["away_team"]
                        total += 1
                        if leader == winner:
                            held += 1
                    if total:
                        insight("Holding the Lead", f"Teams ahead after the 70th minute go on to win {held / total * 100:.0f}% of the time ({held}/{total} matches analyzed).")
                    else:
                        st.caption("Not enough completed matches with a clear 70th-minute leader yet.")


# ---------------------------------------------------------------------------
# Page: Group Standings  (tournament level)
# ---------------------------------------------------------------------------

def standings():
    hero("🏆 Group Standings", "Qualification picture across every group, with knockout zones highlighted.")
    df, ok = safe_load("group_standings.parquet")
    if not ok:
        missing_data_notice("group_standings.parquet", "Once populated: every group renders as a live table with qualification zones highlighted, plus a points-race chart.")
        return

    if "group" not in df.columns:
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    groups_ = sorted(df["group"].dropna().unique().tolist())
    per_row = 3
    for i in range(0, len(groups_), per_row):
        row_groups = groups_[i:i + per_row]
        cols = st.columns(len(row_groups))
        for c, g in zip(cols, row_groups):
            with c:
                st.markdown(f"**Group {g}**")
                gdf = df[df["group"] == g].sort_values(["points", "goal_diff"], ascending=False)
                render_standings_table(gdf)

    if {"team", "points"}.issubset(df.columns):
        st.markdown("#### Points Race — Top 12")
        top = df.sort_values("points", ascending=False).head(12)
        fig = px.bar(top, x="points", y="team", orientation="h", color="points", color_continuous_scale=[INDIGO, CYAN, NEON], title="Highest Points Across All Groups")
        st.plotly_chart(fig_layout(fig), use_container_width=True)


# ---------------------------------------------------------------------------
# Page: Team Intelligence  (team level)
# ---------------------------------------------------------------------------

def team_intelligence():
    radar = load_gold_table("team_radar_stats.parquet")
    metrics = load_gold_table("team_key_metrics.parquet")
    players = load_gold_table("top_players.parquet")
    matches_df, matches_ok = safe_load("matches.parquet")

    teams = metrics[["team_id", "team", "flag", "fifa_rank"]].drop_duplicates().sort_values("team")
    selected = st.selectbox("Select team", teams["team"].tolist(), index=0)
    meta = teams[teams["team"].eq(selected)].iloc[0]

    form_html = '<span style="color:#9DB4C8;">form data pending</span>'
    if matches_ok and {"home_team", "away_team", "home_score", "away_score"}.issubset(matches_df.columns):
        team_matches = matches_df[(matches_df["home_team"] == selected) | (matches_df["away_team"] == selected)].copy()
        if "match_date" in team_matches.columns:
            team_matches = team_matches.sort_values("match_date")
        letters = []
        for _, mrow in team_matches.tail(5).iterrows():
            gf, ga = (mrow["home_score"], mrow["away_score"]) if mrow["home_team"] == selected else (mrow["away_score"], mrow["home_score"])
            if pd.isna(gf) or pd.isna(ga):
                continue
            letters.append("W" if gf > ga else ("L" if gf < ga else "D"))
        if letters:
            form_html = " ".join(result_letter_pill(l) for l in letters)

    st.markdown(f'<div class="hero"><h1>{meta.flag} {selected}</h1><p>FIFA Rank #{int(meta.fifa_rank)} · Recent form {form_html} · Tactical intelligence view</p></div>', unsafe_allow_html=True)

    r = radar[radar["team"].eq(selected)].iloc[0]
    m = metrics[metrics["team"].eq(selected)].iloc[0]

    c1, c2, c3 = st.columns([1, 1, 1.15])
    with c1:
        # Only axes with source-backed values are drawn; null axes are left off rather than estimated.
        axes = [(label, col) for label, col in [("Attack", "attack"), ("Defense", "defense"), ("Possession", "possession"), ("Passing", "passing"), ("Discipline", "discipline")] if has_values(radar, col)]
        cats = [label for label, _ in axes]
        vals = [float(r[col]) if pd.notna(r[col]) else 0.0 for _, col in axes]
        avg_r = radar[[col for _, col in axes]].mean()
        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(r=avg_r.tolist() + [avg_r.tolist()[0]], theta=cats + [cats[0]], line=dict(color=CYAN, width=2, dash="dot"), fillcolor="rgba(0,212,255,.06)", fill="toself", name="Tournament Avg"))
        fig.add_trace(go.Scatterpolar(r=vals + [vals[0]], theta=cats + [cats[0]], fill="toself", line=dict(color=NEON, width=3), fillcolor="rgba(0,245,160,.18)", name=selected))
        fig.update_layout(title="Radar Profile vs Tournament Average", polar=dict(bgcolor="rgba(8,17,31,.7)", radialaxis=dict(visible=True, range=[0, 100], gridcolor="rgba(157,180,200,.15)"), angularaxis=dict(gridcolor="rgba(157,180,200,.15)")), showlegend=True)
        st.plotly_chart(fig_layout(fig), use_container_width=True)
    with c2:
        st.markdown("#### Key Performance Metrics")
        progress_or_na("Expected Goals", m.get("xg"), 3, " xG", digits=2)
        progress_or_na("Shots / Match", m.get("shots_per_match"), 20, "")
        progress_or_na("Possession", m.get("possession_pct"), 100, "%")
        progress_or_na("Pass Accuracy", m.get("pass_accuracy_pct"), 100, "%")
        cards = m.get("cards")
        progress_or_na("Discipline Index", None if cards is None or pd.isna(cards) else max(0, 100 - float(cards) * 4), 100, "%")
    with c3:
        st.markdown("#### Player Contribution")
        if not has_values(players, "player", "goals"):
            unavailable_notice("Goal-scorer data")
        else:
            p = players[players["team"].eq(selected)].sort_values("goals", ascending=False).head(5).copy()
            if p.empty:
                st.caption(f"No goal scorers recorded for {selected}.")
            else:
                show = ["player", "goals"] + (["assists"] if has_values(players, "assists") else [])
                st.dataframe(p[show], use_container_width=True, hide_index=True)

    st.markdown("#### Defensive & Set-Piece Profile")
    d1, d2, d3 = st.columns(3)
    with d1:
        card("Clean Sheets", str(m.get("clean_sheets", "N/A")), "🧱", "season to date")
    with d2:
        card("Goals Against", str(m.get("goals_against", "N/A")), "🥅", "season to date")
    with d3:
        card("Set-Piece Goals", fmt(m.get("setpiece_goals")), "🎯", "corners + free kicks")

    st.markdown("#### Efficiency Checks")
    e1, e2 = st.columns(2)
    with e1:
        delta = float(m.goals_for) - float(m.xg) if pd.notna(m.get("xg")) else None
        if delta is None:
            unavailable_notice("Expected goals (xG)")
        elif delta < -0.5:
            insight("Finishing Concern", f"{selected} are underperforming their underlying chances by {abs(delta):.1f} xG — creating the openings, missing the finish.")
        elif delta > 0.5:
            insight("Finishing Strength", f"{selected} are overperforming their xG by {delta:+.1f} — clinical relative to chance quality.")
        else:
            insight("Finishing in Line with xG", f"{selected}'s goal output ({m.goals_for}) closely tracks their underlying chance quality ({float(m.xg):.1f} xG).")
    with e2:
        poss_rank_s = metrics["possession_pct"].rank(ascending=False, method="min")[metrics["team"] == selected] if "possession_pct" in metrics.columns else pd.Series(dtype=float)
        goals_rank = int(metrics["goals_for"].rank(ascending=False, method="min")[metrics["team"] == selected].iloc[0])
        poss_rank = None if poss_rank_s.empty or pd.isna(poss_rank_s.iloc[0]) else int(poss_rank_s.iloc[0])
        if poss_rank is None:
            unavailable_notice("Possession")
        elif poss_rank <= 10 and goals_rank > 15:
            insight("Possession Without Punch", f"{selected} rank #{poss_rank} for possession but only #{goals_rank} for goals — control isn't converting into a scoreboard edge.")
        else:
            insight("Possession-to-Goals Balance", f"Possession rank #{poss_rank} lines up reasonably with goal-scoring rank #{goals_rank}.")

    if matches_ok and {"home_team", "away_team", "home_score", "away_score", "stage"}.issubset(matches_df.columns):
        team_matches = matches_df[(matches_df["home_team"] == selected) | (matches_df["away_team"] == selected)].copy()
        team_matches["gf"] = team_matches.apply(lambda row: row["home_score"] if row["home_team"] == selected else row["away_score"], axis=1)
        gk_split = team_matches.dropna(subset=["gf"]).groupby("stage")["gf"].mean().reset_index()
        if not gk_split.empty:
            st.markdown("#### Group Stage vs Knockout Form")
            fig = px.bar(gk_split, x="stage", y="gf", color="stage", title=f"{selected} — Avg Goals Scored by Stage", color_discrete_sequence=[INDIGO, NEON, PINK, AMBER])
            fig.update_yaxes(title="Avg Goals Scored")
            st.plotly_chart(fig_layout(fig), use_container_width=True)
    else:
        missing_data_notice("matches.parquet (stage column)", "Once populated: a group-stage vs knockout scoring comparison for this team.")

    st.markdown("#### Team Comparison Matrix")
    if has_values(metrics, "possession_pct", "pass_accuracy_pct"):
        matrix = metrics.dropna(subset=["possession_pct", "pass_accuracy_pct"])
        fig = px.scatter(matrix, x="possession_pct", y="pass_accuracy_pct", size="goals_for", color="xg" if has_values(matrix, "xg") else None, hover_name="team", color_continuous_scale=[INDIGO, CYAN, NEON], title="Possession vs Passing Efficiency")
        st.plotly_chart(fig_layout(fig), use_container_width=True)
    else:
        unavailable_notice("Possession and pass accuracy")


# ---------------------------------------------------------------------------
# Page: Player Leaderboard  (player level)
# ---------------------------------------------------------------------------

def player_leaderboard():
    hero("🥇 Player Leaderboard", "Golden Boot race from source goal events.")
    players, ok = safe_load("top_players.parquet")
    if not ok:
        missing_data_notice("top_players.parquet")
        return

    p = players.copy()
    has_assists = has_values(p, "assists")
    has_xg = has_values(p, "xg")
    p["goals"] = p["goals"].fillna(0) if "goals" in p.columns else 0
    p["contributions"] = p["goals"] + (p["assists"].fillna(0) if has_assists else 0)
    if has_xg:
        p["finishing_delta"] = p["goals"] - p["xg"]

    f1, f2 = st.columns(2)
    with f1:
        teams = ["All"] + sorted(p["team"].dropna().unique().tolist()) if "team" in p.columns else ["All"]
        team_sel = st.selectbox("Filter by team", teams, key="pl_team")
    with f2:
        if "position" in p.columns:
            positions = ["All"] + sorted(p["position"].dropna().unique().tolist())
            pos_sel = st.selectbox("Filter by position", positions, key="pl_pos")
        else:
            pos_sel = "All"
            st.selectbox("Filter by position", ["All — position data pending"], disabled=True, key="pl_pos_disabled")

    view = p.copy()
    if team_sel != "All":
        view = view[view["team"] == team_sel]
    if pos_sel != "All" and "position" in view.columns:
        view = view[view["position"] == pos_sel]

    tab_outfield, tab_more = st.tabs(["⚽ Outfield Leaderboard", "🧤 Goalkeepers & Player Form"])

    with tab_outfield:
        if not view.empty:
            c1, c2, c3 = st.columns(3)
            with c1:
                top_scorer = view.sort_values("goals", ascending=False).iloc[0]
                insight("Golden Boot Leader", f"{top_scorer.player} ({top_scorer.team}) — {int(top_scorer.goals)} goals.")
            with c2:
                if has_assists:
                    top_assist = view.sort_values("assists", ascending=False).iloc[0]
                    insight("Playmaker Leader", f"{top_assist.player} ({top_assist.team}) — {int(top_assist.assists)} assists.")
                else:
                    unavailable_notice("Assist data")
            with c3:
                if has_xg:
                    clinical = view.sort_values("finishing_delta", ascending=False).iloc[0]
                    insight("Most Clinical Finisher", f"{clinical.player} is {clinical.finishing_delta:+.1f} goals ahead of his xG.")
                else:
                    unavailable_notice("Player xG")

        g1, g2 = st.columns(2)
        with g1:
            top10 = view.sort_values("goals", ascending=False).head(10)
            fig = px.bar(top10, x="goals", y="player", orientation="h", color="team", title="Golden Boot Race — Top 10 Scorers")
            st.plotly_chart(fig_layout(fig), use_container_width=True)
        with g2:
            if has_xg:
                fig = px.scatter(view, x="xg", y="goals", size="contributions", color="team", hover_name="player", title="Finishing Quality — Goals vs Expected Goals")
                max_v = float(max(view["xg"].max() if not view.empty else 1, view["goals"].max() if not view.empty else 1, 1))
                fig.add_shape(type="line", x0=0, y0=0, x1=max_v, y1=max_v, line=dict(color="#9DB4C8", dash="dot"))
                st.plotly_chart(fig_layout(fig), use_container_width=True)
            else:
                unavailable_notice("Player xG")

        if has_values(view, "tackles", "interceptions"):
            st.markdown("##### Defensive Workload")
            dview = view.sort_values("tackles", ascending=False).head(10)
            fig = px.bar(dview, x="tackles", y="player", orientation="h", color="interceptions", title="Top 10 — Tackles (color = Interceptions)", color_continuous_scale=[INDIGO, CYAN, NEON])
            st.plotly_chart(fig_layout(fig), use_container_width=True)
        else:
            unavailable_notice("Tackles and interceptions")

        if has_values(view, "rating"):
            st.markdown("##### Player Rating Leaders")
            rview = view.sort_values("rating", ascending=False).head(10)
            fig = px.bar(rview, x="rating", y="player", orientation="h", color="team", title="Top 10 — Average Player Rating")
            st.plotly_chart(fig_layout(fig), use_container_width=True)

        st.markdown("#### Full Leaderboard")
        base_cols = [c for c in ["player", "team", "position", "goals", "assists", "xg", "rating", "pass_accuracy_pct", "tackles", "interceptions"] if c in view.columns]
        show_cols = base_cols + (["finishing_delta"] if has_xg else []) + ["contributions"]
        st.dataframe(view.sort_values("contributions", ascending=False)[show_cols], use_container_width=True, hide_index=True)

    with tab_more:
        unavailable_notice("Goalkeeper saves, player ratings and per-match player stats")


# ---------------------------------------------------------------------------
# Page: Venues & Cities
# ---------------------------------------------------------------------------

def venues_cities():
    hero("🌆 Venues & Host Cities", "Stadium workload and geography across Canada, Mexico and the USA.")
    cities, ok = safe_load("host_cities.parquet")
    if not ok:
        missing_data_notice("host_cities.parquet")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        insight("Host Footprint", f"{cities['city'].nunique()} cities across {cities['country'].nunique()} countries are staging matches.")
    with c2:
        busiest = cities.sort_values("matches", ascending=False).iloc[0]
        insight("Busiest Stadium", f"{busiest.stadium} in {busiest.city} hosts the most matches ({int(busiest.matches)}).")
    with c3:
        by_country = cities.groupby("country")["matches"].sum().sort_values(ascending=False)
        insight("Matches by Host Nation", " · ".join(f"{k}: {int(v)}" for k, v in by_country.items()))

    m1, m2 = st.columns([1.3, .7])
    with m1:
        mapped = cities.dropna(subset=["lat", "lon"]) if {"lat", "lon"}.issubset(cities.columns) else pd.DataFrame()
        if mapped.empty:
            unavailable_notice("Stadium coordinates")
        else:
            fig = px.scatter_mapbox(mapped, lat="lat", lon="lon", size="matches", color="country", hover_name="city", hover_data=["stadium", "matches"], zoom=2.2, height=480, title="Stadium Workload Map")
            fig.update_layout(mapbox_style="carto-darkmatter", mapbox=dict(center={"lat": 38, "lon": -96}), margin=dict(l=0, r=0, t=45, b=0))
            st.plotly_chart(fig_layout(fig), use_container_width=True)
    with m2:
        ranked = cities.sort_values("matches", ascending=True)
        fig = px.bar(ranked, x="matches", y="stadium", orientation="h", color="country", title="Stadiums Ranked by Matches Hosted")
        st.plotly_chart(fig_layout(fig), use_container_width=True)

    st.markdown("#### All Venues")
    st.dataframe(cities.sort_values("matches", ascending=False), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

mock_banner = begin_mock_tracking()
try:
    page = sidebar()
    if page == "⚽ Overview":
        overview()
    elif page == "🏟️ Match Center":
        match_center()
    elif page == "🏆 Group Standings":
        standings()
    elif page == "📊 Team Intelligence":
        team_intelligence()
    elif page == "🥇 Player Leaderboard":
        player_leaderboard()
    else:
        venues_cities()
finally:
    render_mock_banner(mock_banner)