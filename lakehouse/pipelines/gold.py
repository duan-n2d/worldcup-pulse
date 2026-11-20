from __future__ import annotations

import pandas as pd

from common import GOLD_DIR, SILVER_DIR, read_parquet, write_parquet

MINUTE_BUCKETS = ["0-15'", "16-30'", "31-45'(+45)", "46-60'", "61-75'", "76-90'(+90)"]


def _bucket(minute: int) -> str:
    if minute <= 15:
        return "0-15'"
    if minute <= 30:
        return "16-30'"
    if minute <= 45:
        return "31-45'(+45)"
    if minute <= 60:
        return "46-60'"
    if minute <= 75:
        return "61-75'"
    return "76-90'(+90)"


def _safe_int(value, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def _norm_status(row: pd.Series) -> str:
    raw = str(row.get("status", "") or "").lower()
    if any(x in raw for x in ["live", "in progress", "playing"]):
        return "live"
    if pd.notna(row.get("home_score")) and pd.notna(row.get("away_score")):
        return "completed"
    if any(x in raw for x in ["finish", "complete", "ft", "ended"]):
        return "completed"
    return "scheduled"


def _optional_float(value) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _mean_or_none(df: pd.DataFrame, col: str) -> float | None:
    if df.empty or col not in df.columns:
        return None
    value = pd.to_numeric(df[col], errors="coerce").mean()
    return None if pd.isna(value) else round(float(value), 1)


def _count_events(events: pd.DataFrame, pattern: str) -> int | None:
    """Count source events whose type matches ``pattern``; None when the source reports none."""
    if events.empty or "event_type" not in events.columns:
        return None
    n = int(events["event_type"].astype(str).str.contains(pattern, case=False, na=False, regex=True).sum())
    return n or None


def _stage_order(stage: str) -> int:
    s = str(stage or "").upper()
    order = {"GROUP": 1, "R32": 2, "R16": 3, "QF": 4, "SF": 5, "3RD": 6, "FINAL": 7}
    for key, val in order.items():
        if key in s:
            return val
    return 1


def _empty_outputs() -> dict[str, pd.DataFrame]:
    return {
        "kpi_summary": pd.DataFrame([{"matches_played": 0, "total_goals": 0, "avg_goals_per_match": 0, "biggest_win": "N/A", "most_offensive_team": "N/A", "most_defensive_team": "N/A", "avg_possession": None, "cards_per_match": None, "matches_remaining": 104, "total_yellow_cards": None, "total_red_cards": None, "penalties_awarded": None, "var_goals": None}]),
        "goals_by_matchday": pd.DataFrame({"matchday": [1], "goals": [0], "matches": [0]}),
        "goals_by_minute_bucket": pd.DataFrame({"minute_bucket": MINUTE_BUCKETS, "goals": [0] * len(MINUTE_BUCKETS)}),
        "host_cities": pd.DataFrame(),
        "team_radar_stats": pd.DataFrame(),
        "team_key_metrics": pd.DataFrame(),
        "top_players": pd.DataFrame(),
        "team_table": pd.DataFrame(),
        "matches": pd.DataFrame(),
        "group_standings": pd.DataFrame(),
        "match_events": pd.DataFrame(),
    }


def _build_gold_matches(matches: pd.DataFrame, teams: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    if matches.empty:
        return pd.DataFrame()
    team_lu = teams.set_index("team_id").to_dict("index") if not teams.empty and "team_id" in teams.columns else {}
    xg_lu: dict[tuple[str, str], float] = {}
    if not stats.empty and {"match_id", "team_id", "xg"}.issubset(stats.columns):
        for _, r in stats.iterrows():
            xg = _optional_float(r.get("xg"))
            xg_lu[(str(r["match_id"]), str(r["team_id"]))] = None if xg is None else round(xg, 2)
    rows = []
    for _, m in matches.iterrows():
        home_id = str(m.get("home_team_id", ""))
        away_id = str(m.get("away_team_id", ""))
        home_meta = team_lu.get(home_id, {})
        away_meta = team_lu.get(away_id, {})
        md = _safe_int(m.get("matchday"), 1)
        kickoff = str(m.get("kickoff_utc", "") or "")
        match_date = kickoff[:10] if len(kickoff) >= 10 and kickoff[:4].isdigit() else None
        rows.append({
            "match_id": str(m.get("match_id", "")),
            "matchday": md,
            "stage": str(m.get("stage", "Group")),
            "group": home_meta.get("group_name", "Unknown"),
            "match_date": match_date,
            "kickoff_local": kickoff[11:16] if len(kickoff) >= 16 else None,
            "venue": str(m.get("stadium", "Unknown Stadium")),
            "city": str(m.get("city", "Unknown")),
            "home_team": home_meta.get("team", m.get("home_team_label", home_id)),
            "home_flag": home_meta.get("flag", ""),
            "away_team": away_meta.get("team", m.get("away_team_label", away_id)),
            "away_flag": away_meta.get("flag", ""),
            "home_score": m.get("home_score"),
            "away_score": m.get("away_score"),
            "home_xg": xg_lu.get((str(m.get("match_id", "")), home_id), None),
            "away_xg": xg_lu.get((str(m.get("match_id", "")), away_id), None),
            "attendance": _safe_int(m.get("attendance"), None) if pd.notna(m.get("attendance")) else None,
            "status": _norm_status(m),
        })
    return pd.DataFrame(rows).sort_values(["matchday", "match_id"]).reset_index(drop=True)


def _build_team_tables(teams: pd.DataFrame, stats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_cols = ["team_id", "team", "flag", "fifa_rank", "group_name"]
    team_names = teams[[c for c in base_cols if c in teams.columns]].copy() if not teams.empty else pd.DataFrame(columns=base_cols)
    if stats.empty:
        team_agg = pd.DataFrame(columns=["team_id", "played", "goals_for", "goals_against", "xg", "shots", "possession_pct", "pass_accuracy_pct", "cards", "clean_sheets"])
    else:
        tmp = stats.copy()
        tmp["clean_sheet"] = (tmp.get("goals_against", 0).fillna(0).astype(float) == 0).astype(int)
        for col in ["xg", "shots", "possession_pct", "pass_accuracy_pct", "cards"]:
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce") if col in tmp.columns else float("nan")
        # Source-only stats stay null when the API never reported them (min_count=1 keeps an all-null sum null).
        team_agg = tmp.groupby("team_id", as_index=False).agg(
            played=("match_id", "nunique"),
            goals_for=("goals_for", "sum"),
            goals_against=("goals_against", "sum"),
            xg=("xg", "mean"),
            shots=("shots", "mean"),
            possession_pct=("possession_pct", "mean"),
            pass_accuracy_pct=("pass_accuracy_pct", "mean"),
            cards=("cards", lambda s: s.sum(min_count=1)),
            clean_sheets=("clean_sheet", "sum"),
        )
    team_table = team_names.merge(team_agg, on="team_id", how="left")
    fill = {"played": 0, "goals_for": 0, "goals_against": 0, "clean_sheets": 0}
    team_table = team_table.fillna(fill)
    if "group_name" not in team_table.columns:
        team_table["group_name"] = "Unknown"
    team_table["shots_per_match"] = pd.to_numeric(team_table["shots"], errors="coerce").round(1)
    # The source API has no set-piece breakdown, so this stays null rather than being estimated.
    team_table["setpiece_goals"] = pd.Series([None] * len(team_table), dtype="Int64")

    radar = team_table.copy()
    if not radar.empty:
        # Attack/defense are derived from real goal tallies; the other axes are null unless the source reports them.
        radar["attack"] = (radar["goals_for"].astype(float) * 18).clip(0, 100).round(1)
        radar["defense"] = (100 - radar["goals_against"].astype(float) * 15).clip(20, 100).round(1)
        radar["possession"] = pd.to_numeric(radar["possession_pct"], errors="coerce").clip(0, 100).round(1)
        radar["passing"] = pd.to_numeric(radar["pass_accuracy_pct"], errors="coerce").clip(0, 100).round(1)
        radar["discipline"] = (100 - pd.to_numeric(radar["cards"], errors="coerce") * 4).clip(20, 100).round(1)
    team_radar_stats = radar[["team_id", "team", "flag", "fifa_rank", "attack", "defense", "possession", "passing", "discipline"]] if not radar.empty else pd.DataFrame()
    team_key_metrics = team_table[["team_id", "team", "flag", "fifa_rank", "xg", "shots_per_match", "possession_pct", "pass_accuracy_pct", "goals_for", "goals_against", "cards", "clean_sheets", "setpiece_goals"]] if not team_table.empty else pd.DataFrame()
    return team_table, team_radar_stats, team_key_metrics


def _build_events(events: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
    cols = ["event_id", "match_id", "minute", "half", "event_type", "team_id", "team", "player", "assist_player", "shot_x", "shot_y"]
    if events.empty:
        return pd.DataFrame(columns=cols)
    team_lu = teams.set_index("team_id").to_dict("index") if not teams.empty and "team_id" in teams.columns else {}
    rows = []
    for _, ev in events.iterrows():
        team_id = str(ev.get("team_id", ""))
        minute = _safe_int(ev.get("minute"), None) if pd.notna(ev.get("minute")) else None
        etype = str(ev.get("event_type", "goal") or "goal")
        player = ev.get("player")
        assist = ev.get("assist_player")
        rows.append({
            "event_id": str(ev.get("event_id", "")),
            "match_id": str(ev.get("match_id", "")),
            "minute": minute,
            "half": None if minute is None else (1 if minute <= 45 else 2),
            "event_type": etype,
            "team_id": team_id,
            "team": team_lu.get(team_id, {}).get("team", team_id),
            "player": player if isinstance(player, str) and player else None,
            "assist_player": assist if isinstance(assist, str) and assist else None,
            # The source API has no shot coordinates; kept as null columns for schema stability.
            "shot_x": None,
            "shot_y": None,
        })
    return pd.DataFrame(rows, columns=cols)


def _build_top_players(events_gold: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    """Goal (and, when the source names assisters, assist) tallies from real goal events only.

    Ratings, xG, distance, sprint speed, tackles and interceptions are not in the
    source API, so they are not produced at all.
    """
    cols = ["player", "team_id", "team", "position", "goals", "assists"]
    if events_gold.empty or "player" not in events_gold.columns:
        return pd.DataFrame(columns=cols)
    goal_events = events_gold[events_gold["event_type"].astype(str).str.contains("goal", case=False, na=False) & events_gold["player"].notna()]
    if goal_events.empty:
        return pd.DataFrame(columns=cols)
    base = goal_events.groupby(["player", "team_id", "team"], as_index=False).agg(goals=("event_id", "count"))
    assists_known = "assist_player" in goal_events.columns and goal_events["assist_player"].notna().any()
    if assists_known:
        assists = goal_events.dropna(subset=["assist_player"]).groupby(["assist_player", "team_id"], as_index=False).agg(assists=("event_id", "count")).rename(columns={"assist_player": "player"})
        base = base.merge(assists, on=["player", "team_id"], how="outer")
        base["team"] = base["team"].fillna(base["team_id"])
        base["goals"] = base["goals"].fillna(0).astype(int)
        base["assists"] = base["assists"].fillna(0).astype(int)
    else:
        base["assists"] = pd.Series([None] * len(base), dtype="Int64")
    position_lu = players.drop_duplicates(["player", "team_id"]).set_index(["player", "team_id"])["position"].to_dict() if not players.empty and {"player", "team_id", "position"}.issubset(players.columns) else {}
    base["position"] = [position_lu.get((p, t)) for p, t in zip(base["player"], base["team_id"])]
    return base[cols].sort_values(["goals", "assists"], ascending=False, na_position="last").reset_index(drop=True)


def _build_group_standings(teams: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    if teams.empty:
        return pd.DataFrame()
    standings = []
    stats2 = stats.copy() if not stats.empty else pd.DataFrame(columns=["team_id", "goals_for", "goals_against"])
    for _, team in teams.iterrows():
        tid = team.get("team_id")
        tstats = stats2[stats2["team_id"] == tid] if "team_id" in stats2.columns else pd.DataFrame()
        played = len(tstats)
        won = int((tstats["goals_for"] > tstats["goals_against"]).sum()) if not tstats.empty else 0
        drawn = int((tstats["goals_for"] == tstats["goals_against"]).sum()) if not tstats.empty else 0
        lost = int((tstats["goals_for"] < tstats["goals_against"]).sum()) if not tstats.empty else 0
        gf = int(tstats["goals_for"].sum()) if not tstats.empty else 0
        ga = int(tstats["goals_against"].sum()) if not tstats.empty else 0
        points = won * 3 + drawn
        standings.append({
            "group": team.get("group_name", "Unknown"),
            "team": team.get("team", tid),
            "flag": team.get("flag", ""),
            "played": played,
            "won": won,
            "drawn": drawn,
            "lost": lost,
            "goals_for": gf,
            "goals_against": ga,
            "goal_diff": gf - ga,
            "points": points,
            "qualification_status": "qualified" if points >= 6 else ("in_contention" if played < 3 else "eliminated"),
        })
    df = pd.DataFrame(standings)
    if not df.empty:
        df = df.sort_values(["group", "points", "goal_diff", "goals_for"], ascending=[True, False, False, False]).reset_index(drop=True)
    return df


def build_gold() -> dict[str, pd.DataFrame]:
    teams = read_parquet(SILVER_DIR / "teams.parquet")
    matches = read_parquet(SILVER_DIR / "matches.parquet")
    stats = read_parquet(SILVER_DIR / "team_match_stats.parquet")
    events = read_parquet(SILVER_DIR / "events.parquet")
    players = read_parquet(SILVER_DIR / "players.parquet")
    stadiums = read_parquet(SILVER_DIR / "stadiums.parquet")

    if teams.empty and matches.empty:
        outputs = _empty_outputs()
        for name, df in outputs.items():
            write_parquet(df, GOLD_DIR / f"{name}.parquet")
        return outputs

    matches_gold = _build_gold_matches(matches, teams, stats)
    played = matches_gold[matches_gold["status"].eq("completed")].copy() if not matches_gold.empty and "status" in matches_gold.columns else pd.DataFrame()
    total_goals = int((played["home_score"].fillna(0) + played["away_score"].fillna(0)).sum()) if not played.empty else 0
    match_count = int(len(played))
    avg_goals = round(total_goals / match_count, 2) if match_count else 0
    biggest_win = "N/A"
    if not played.empty:
        played["goal_diff"] = (played["home_score"].fillna(0) - played["away_score"].fillna(0)).abs()
        r = played.sort_values("goal_diff", ascending=False).iloc[0]
        biggest_win = f"{r['home_team']} {int(r['home_score'])}-{int(r['away_score'])} {r['away_team']}"

    team_table, team_radar_stats, team_key_metrics = _build_team_tables(teams, stats)
    match_events = _build_events(events, teams)
    total_cards = _optional_float(pd.to_numeric(stats["cards"], errors="coerce").sum(min_count=1)) if not stats.empty and "cards" in stats.columns else None
    most_offensive = team_table.sort_values("goals_for", ascending=False).iloc[0]["team"] if not team_table.empty else "N/A"
    most_defensive = team_table.sort_values("goals_against", ascending=True).iloc[0]["team"] if not team_table.empty else "N/A"
    kpi_summary = pd.DataFrame([{
        "matches_played": match_count,
        "total_goals": total_goals,
        "avg_goals_per_match": avg_goals,
        "biggest_win": biggest_win,
        "most_offensive_team": most_offensive,
        "most_defensive_team": most_defensive,
        "avg_possession": _mean_or_none(stats, "possession_pct"),
        "cards_per_match": round(total_cards / match_count, 2) if match_count and total_cards is not None else None,
        "matches_remaining": max(0, len(matches_gold) - match_count),
        # Card / penalty / VAR counts only come from source events; null when the API does not report them.
        "total_yellow_cards": _count_events(match_events, "yellow"),
        "total_red_cards": _count_events(match_events, "red"),
        "penalties_awarded": _count_events(match_events, "penalty"),
        "var_goals": _count_events(match_events, "var"),
    }])

    goals_by_matchday = played.assign(goals=played["home_score"].fillna(0) + played["away_score"].fillna(0)).groupby("matchday", as_index=False).agg(goals=("goals", "sum"), matches=("match_id", "count")) if not played.empty else pd.DataFrame({"matchday": [1], "goals": [0], "matches": [0]})
    if match_events.empty or match_events["minute"].notna().sum() == 0:
        goals_by_minute = pd.DataFrame({"minute_bucket": MINUTE_BUCKETS, "goals": [0] * len(MINUTE_BUCKETS)})
    else:
        ev = match_events[match_events["event_type"].astype(str).str.contains("goal", case=False, na=False) & match_events["minute"].notna()].copy()
        ev["minute_bucket"] = ev["minute"].astype(int).map(_bucket)
        goals_by_minute = ev.groupby("minute_bucket", as_index=False).agg(goals=("event_id", "count"))
        goals_by_minute = pd.DataFrame({"minute_bucket": MINUTE_BUCKETS}).merge(goals_by_minute, on="minute_bucket", how="left").fillna({"goals": 0})

    if not matches.empty:
        host_cities = matches.groupby(["city", "stadium"], as_index=False).agg(matches=("match_id", "count"))
        host_cities = host_cities.merge(stadiums[["stadium", "country", "lat", "lon"]], on="stadium", how="left") if not stadiums.empty and "stadium" in stadiums.columns else host_cities
        # Coordinates stay null when the source has none for a stadium (no placeholder location).
        for col in ["country", "lat", "lon"]:
            if col not in host_cities.columns:
                host_cities[col] = None
    else:
        host_cities = pd.DataFrame()

    top_players = _build_top_players(match_events, players)
    group_standings = _build_group_standings(teams, stats)

    outputs = {
        "kpi_summary": kpi_summary,
        "goals_by_matchday": goals_by_matchday,
        "goals_by_minute_bucket": goals_by_minute,
        "host_cities": host_cities,
        "team_radar_stats": team_radar_stats,
        "team_key_metrics": team_key_metrics,
        "top_players": top_players,
        "team_table": team_table,
        "matches": matches_gold,
        "group_standings": group_standings,
        "match_events": match_events,
    }
    for name, df in outputs.items():
        write_parquet(df, GOLD_DIR / f"{name}.parquet")
    return outputs
