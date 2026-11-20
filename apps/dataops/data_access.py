from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import duckdb
import numpy as np
import pandas as pd
import streamlit as st
from huggingface_hub import hf_hub_download

HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "your-username/worldcup-pulse-data")
HF_TOKEN = os.environ.get("HF_TOKEN")

# Tables that fell back to mock data during the current script run, with the reason.
_MOCK_STATE_KEY = "_worldcup_pulse_mock_tables"

TEAMS = [
    ("CAN", "Canada", "🇨🇦", 31, "A"), ("MEX", "Mexico", "🇲🇽", 15, "A"), ("USA", "United States", "🇺🇸", 11, "B"),
    ("BRA", "Brazil", "🇧🇷", 5, "C"), ("FRA", "France", "🇫🇷", 2, "D"), ("ARG", "Argentina", "🇦🇷", 1, "E"),
    ("ENG", "England", "🏴", 4, "F"), ("ESP", "Spain", "🇪🇸", 8, "G"), ("GER", "Germany", "🇩🇪", 10, "H"),
    ("POR", "Portugal", "🇵🇹", 6, "I"), ("JPN", "Japan", "🇯🇵", 18, "J"), ("URU", "Uruguay", "🇺🇾", 14, "K"),
]


def _download(path_in_repo: str) -> str:
    return hf_hub_download(repo_id=HF_DATASET_REPO, repo_type="dataset", filename=path_in_repo, token=HF_TOKEN)


def begin_mock_tracking():
    """Call once at the top of the app script; returns the slot the mock-data banner renders into."""
    st.session_state[_MOCK_STATE_KEY] = {}
    return st.empty()


def _record_mock(name: str, reason: str) -> None:
    st.session_state.setdefault(_MOCK_STATE_KEY, {})[name] = reason


def render_mock_banner(slot) -> None:
    """Fill the banner slot if any table on this run was served from mock data."""
    mocked = st.session_state.get(_MOCK_STATE_KEY) or {}
    if not mocked:
        return
    tables = ", ".join(f"`{name}`" for name in sorted(mocked))
    reason = next(iter(mocked.values()))
    slot.warning(
        f"**MOCK DATA — not real tournament results.** The Hugging Face dataset `{HF_DATASET_REPO}` could not be read, "
        f"so these tables show built-in sample values: {tables}. First error: {reason}",
        icon="⚠️",
    )


@st.cache_data(ttl=300, show_spinner=False)
def _load_gold_cached(filename: str) -> tuple[pd.DataFrame, str | None]:
    try:
        path = _download(f"gold/{filename}")
        return duckdb.sql(f"SELECT * FROM '{path}'").df(), None
    except Exception as exc:
        mock = _mock_fallback(filename)
        if mock is None:
            raise
        return mock, f"{type(exc).__name__}: {exc}"


def load_gold_table(filename: str) -> pd.DataFrame:
    """Read a gold mart from the HF dataset; on failure, serve mock data and flag it for the banner.

    Tables without a mock (marts the pipeline no longer produces) re-raise the error.
    """
    df, mock_reason = _load_gold_cached(filename)
    if mock_reason:
        _record_mock(filename, mock_reason)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def _load_log_cached(filename: str) -> tuple[pd.DataFrame, str | None]:
    try:
        path = _download(f"logs/{filename}")
        return pd.read_csv(path), None
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        if filename == "pipeline_runs.csv":
            now = datetime.now(timezone.utc).isoformat()
            return pd.DataFrame([
                {"run_id": "mock_002", "started_at": now, "finished_at": now, "status": "Success", "rows_bronze": 408, "rows_silver": 312, "rows_gold": 256, "error_message": "mock fallback"},
                {"run_id": "mock_001", "started_at": (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat(), "finished_at": now, "status": "QualityFailed", "rows_bronze": 390, "rows_silver": 310, "rows_gold": 240, "error_message": "sample warning"},
            ]), reason
        return _mock_quality(), reason


def load_log_table(filename: str) -> pd.DataFrame:
    df, mock_reason = _load_log_cached(filename)
    if mock_reason:
        _record_mock(filename, mock_reason)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def download_gold_path(filename: str) -> str | None:
    try:
        return _download(f"gold/{filename}")
    except Exception:
        return None


def _teams() -> pd.DataFrame:
    return pd.DataFrame([{"team_id": a, "team": b, "flag": c, "fifa_rank": d, "group_name": e} for a, b, c, d, e in TEAMS])


def _rng(seed: int = 2026) -> np.random.Generator:
    return np.random.default_rng(seed)


def _mock_matches() -> pd.DataFrame:
    teams = _teams()
    rows = []
    start = datetime(2026, 6, 11)
    pairs = [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11), (0, 3), (1, 2), (4, 7), (5, 6), (8, 11), (9, 10)]
    stadiums = _mock_fallback("host_cities.parquet")
    for idx, (h, a) in enumerate(pairs, start=1):
        home = teams.iloc[h]
        away = teams.iloc[a]
        st_row = stadiums.iloc[(idx - 1) % len(stadiums)]
        hs = int((idx * 2 + h) % 4)
        aw = int((idx + a) % 3)
        rows.append({
            "match_id": f"M{idx:03d}", "matchday": (idx - 1) // 4 + 1, "stage": "Group", "group": home.group_name,
            "match_date": (start + timedelta(days=(idx - 1) // 4)).date().isoformat(), "kickoff_local": "20:00",
            "venue": st_row.stadium, "city": st_row.city,
            "home_team": home.team, "home_flag": home.flag, "away_team": away.team, "away_flag": away.flag,
            "home_score": hs, "away_score": aw, "home_xg": round(max(0.2, hs * .75 + .6), 2), "away_xg": round(max(0.2, aw * .75 + .4), 2),
            "attendance": 48000 + idx * 1200, "status": "completed" if idx <= 10 else "scheduled",
        })
    return pd.DataFrame(rows)


def _mock_fallback(filename: str) -> pd.DataFrame | None:
    teams = _teams()
    rng = _rng()
    if filename == "kpi_summary.parquet":
        return pd.DataFrame([{"matches_played": 48, "total_goals": 142, "avg_goals_per_match": 2.96, "biggest_win": "Brazil 4-0 Canada", "most_offensive_team": "Brazil", "most_defensive_team": "France", "avg_possession": 53.4, "cards_per_match": 3.1, "matches_remaining": 56, "total_yellow_cards": 166, "total_red_cards": 8, "penalties_awarded": 17, "var_goals": 11}])
    if filename == "goals_by_matchday.parquet":
        return pd.DataFrame({"matchday": list(range(1, 13)), "goals": [8, 11, 13, 9, 15, 12, 14, 10, 16, 13, 11, 10], "matches": [4] * 12})
    if filename == "goals_by_minute_bucket.parquet":
        return pd.DataFrame({"minute_bucket": ["0-15'", "16-30'", "31-45'(+45)", "46-60'", "61-75'", "76-90'(+90)"], "goals": [18, 22, 26, 19, 24, 33]})
    if filename == "host_cities.parquet":
        return pd.DataFrame([
            {"city": "New York/New Jersey", "stadium": "MetLife Stadium", "country": "USA", "matches": 8, "lat": 40.8135, "lon": -74.0745},
            {"city": "Mexico City", "stadium": "Estadio Azteca", "country": "Mexico", "matches": 5, "lat": 19.3029, "lon": -99.1505},
            {"city": "Vancouver", "stadium": "BC Place", "country": "Canada", "matches": 7, "lat": 49.2768, "lon": -123.1119},
            {"city": "Los Angeles", "stadium": "SoFi Stadium", "country": "USA", "matches": 8, "lat": 33.9535, "lon": -118.3392},
            {"city": "Toronto", "stadium": "BMO Field", "country": "Canada", "matches": 6, "lat": 43.6332, "lon": -79.4186},
            {"city": "Guadalajara", "stadium": "Estadio Akron", "country": "Mexico", "matches": 4, "lat": 20.6818, "lon": -103.4626},
        ])
    if filename == "team_radar_stats.parquet":
        out = teams.copy()
        for col in ["attack", "defense", "possession", "passing", "discipline"]:
            out[col] = rng.integers(55, 96, size=len(out))
        return out
    if filename == "team_key_metrics.parquet":
        out = teams.copy()
        out["xg"] = np.round(rng.uniform(1.1, 2.8, len(out)), 2)
        out["shots_per_match"] = np.round(rng.uniform(8, 18, len(out)), 1)
        out["possession_pct"] = rng.integers(43, 66, len(out))
        out["pass_accuracy_pct"] = rng.integers(76, 92, len(out))
        out["goals_for"] = rng.integers(3, 14, len(out))
        out["goals_against"] = rng.integers(1, 8, len(out))
        out["cards"] = rng.integers(3, 14, len(out))
        out["clean_sheets"] = rng.integers(0, 4, len(out))
        out["setpiece_goals"] = rng.integers(0, 5, len(out))
        return out
    if filename == "top_players.parquet":
        rows = []
        for _, t in teams.iterrows():
            for idx in range(1, 6):
                seed = sum(ord(c) for c in f"{t.team}{idx}")
                rows.append({"player": f"{t.team} Player {idx}", "team_id": t.team_id, "team": t.team, "position": ["FW", "MF", "FW", "DF", "MF"][idx - 1], "goals": max(0, 6 - idx), "assists": max(0, 4 - idx), "xg": round(3.2 - idx * 0.35, 2), "rating": round(6.4 + (seed % 20) / 10, 2), "distance_km": round(8.7 + (seed % 30) / 10, 1), "sprint_speed_kmh": round(29 + (seed % 55) / 10, 1), "pass_accuracy_pct": 72 + seed % 24, "tackles": seed % 9, "interceptions": (seed // 3) % 8})
        return pd.DataFrame(rows)
    if filename == "team_table.parquet":
        return _mock_fallback("team_key_metrics.parquet")
    if filename == "matches.parquet":
        return _mock_matches()
    if filename == "group_standings.parquet":
        rows = []
        for _, t in teams.iterrows():
            seed = sum(ord(c) for c in t.team_id)
            won = seed % 3
            drawn = (seed // 3) % 2
            lost = max(0, 3 - won - drawn)
            gf = 2 + seed % 8
            ga = seed % 5
            rows.append({"group": t.group_name, "team": t.team, "flag": t.flag, "played": 3, "won": won, "drawn": drawn, "lost": lost, "goals_for": gf, "goals_against": ga, "goal_diff": gf - ga, "points": won * 3 + drawn, "qualification_status": "qualified" if won * 3 + drawn >= 6 else "in_contention"})
        return pd.DataFrame(rows).sort_values(["group", "points", "goal_diff"], ascending=[True, False, False])
    if filename == "match_events.parquet":
        matches = _mock_matches()
        rows = []
        for _, m in matches.iterrows():
            for team_col, score_col in [("home_team", "home_score"), ("away_team", "away_score")]:
                score = int(m[score_col]) if pd.notna(m[score_col]) else 0
                for g in range(score):
                    minute = 12 + ((g * 17 + int(m.matchday) * 5) % 78)
                    seed = sum(ord(c) for c in f"{m.match_id}{team_col}{g}")
                    rows.append({"event_id": f"{m.match_id}_{team_col}_{g+1}", "match_id": m.match_id, "minute": minute, "half": 1 if minute <= 45 else 2, "event_type": "goal", "team": m[team_col], "team_id": str(m[team_col])[:3].upper(), "player": f"{m[team_col]} Player {g+1}", "assist_player": f"{m[team_col]} Creator {g+1}", "shot_x": 68 + seed % 24, "shot_y": 18 + seed % 64})
        return pd.DataFrame(rows)
    # No mock for marts the pipeline does not produce (they used to be synthetic).
    return None


def _mock_quality() -> pd.DataFrame:
    rows = []
    for layer in ["Bronze", "Silver", "Gold"]:
        for table in ["teams", "matches", "events", "kpi_summary", "match_events", "group_standings"]:
            rows.append({"checked_at": datetime.now(timezone.utc).isoformat(), "layer": layer, "table": table, "check_name": "not_empty", "status": "Pass", "message": "mock fallback pass"})
    return pd.DataFrame(rows)
