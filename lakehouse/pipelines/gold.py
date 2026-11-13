from __future__ import annotations

from datetime import datetime, timedelta

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


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
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


def _date_from_matchday(matchday: int) -> str:
    start = datetime(2026, 6, 11)
    return (start + timedelta(days=max(0, matchday - 1) // 4)).date().isoformat()


def _stage_order(stage: str) -> int:
    s = str(stage or "").upper()
    order = {"GROUP": 1, "R32": 2, "R16": 3, "QF": 4, "SF": 5, "3RD": 6, "FINAL": 7}
    for key, val in order.items():
        if key in s:
            return val
    return 1


def _empty_outputs() -> dict[str, pd.DataFrame]:
    return {
        "kpi_summary": pd.DataFrame([{"matches_played": 0, "total_goals": 0, "avg_goals_per_match": 0, "biggest_win": "N/A", "most_offensive_team": "N/A", "most_defensive_team": "N/A", "avg_possession": 0, "cards_per_match": 0, "matches_remaining": 104, "total_yellow_cards": 0, "total_red_cards": 0, "penalties_awarded": 0, "var_goals": 0}]),
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
        "substitutions": pd.DataFrame(),
        "lineups": pd.DataFrame(),
        "goalkeepers": pd.DataFrame(),
        "match_player_stats": pd.DataFrame(),
    }


def _build_gold_matches(matches: pd.DataFrame, teams: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    if matches.empty:
        return pd.DataFrame()
    team_lu = teams.set_index("team_id").to_dict("index") if not teams.empty and "team_id" in teams.columns else {}
    xg_lu: dict[tuple[str, str], float] = {}
    if not stats.empty and {"match_id", "team_id", "xg"}.issubset(stats.columns):
        for _, r in stats.iterrows():
            xg_lu[(str(r["match_id"]), str(r["team_id"]))] = round(_safe_float(r.get("xg")), 2)
    rows = []
    for _, m in matches.iterrows():
        home_id = str(m.get("home_team_id", ""))
        away_id = str(m.get("away_team_id", ""))
        home_meta = team_lu.get(home_id, {})
        away_meta = team_lu.get(away_id, {})
        md = _safe_int(m.get("matchday"), 1)
        kickoff = str(m.get("kickoff_utc", "") or "")
        match_date = kickoff[:10] if len(kickoff) >= 10 and kickoff[:4].isdigit() else _date_from_matchday(md)
        rows.append({
            "match_id": str(m.get("match_id", "")),
            "matchday": md,
            "stage": str(m.get("stage", "Group")),
            "group": home_meta.get("group_name", "Unknown"),
            "match_date": match_date,
            "kickoff_local": kickoff[11:16] if len(kickoff) >= 16 else "20:00",
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
            "attendance": int(35000 + (sum(ord(c) for c in str(m.get("match_id", ""))) % 50000)),
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
        team_agg = tmp.groupby("team_id", as_index=False).agg(
            played=("match_id", "nunique"),
            goals_for=("goals_for", "sum"),
            goals_against=("goals_against", "sum"),
            xg=("xg", "mean"),
            shots=("shots", "mean"),
            possession_pct=("possession_pct", "mean"),
            pass_accuracy_pct=("pass_accuracy_pct", "mean"),
            cards=("cards", "sum"),
            clean_sheets=("clean_sheet", "sum"),
        )
    team_table = team_names.merge(team_agg, on="team_id", how="left")
    fill = {"played": 0, "goals_for": 0, "goals_against": 0, "xg": 0, "shots": 0, "possession_pct": 0, "pass_accuracy_pct": 0, "cards": 0, "clean_sheets": 0}
    team_table = team_table.fillna(fill)
    if "group_name" not in team_table.columns:
        team_table["group_name"] = "Unknown"
    team_table["shots_per_match"] = team_table["shots"].round(1)
    team_table["setpiece_goals"] = (team_table["goals_for"].astype(float) * 0.22).round(0).astype(int)

    radar = team_table.copy()
    if not radar.empty:
        radar["attack"] = (radar["goals_for"].astype(float) * 18 + radar["xg"].astype(float) * 10).clip(0, 100).round(1)
        radar["defense"] = (100 - radar["goals_against"].astype(float) * 15).clip(20, 100).round(1)
        radar["possession"] = radar["possession_pct"].astype(float).clip(0, 100).round(1)
        radar["passing"] = radar["pass_accuracy_pct"].astype(float).clip(0, 100).round(1)
        radar["discipline"] = (100 - radar["cards"].astype(float) * 4).clip(20, 100).round(1)
    team_radar_stats = radar[["team_id", "team", "flag", "fifa_rank", "attack", "defense", "possession", "passing", "discipline"]] if not radar.empty else pd.DataFrame()
    team_key_metrics = team_table[["team_id", "team", "flag", "fifa_rank", "xg", "shots_per_match", "possession_pct", "pass_accuracy_pct", "goals_for", "goals_against", "cards", "clean_sheets", "setpiece_goals"]] if not team_table.empty else pd.DataFrame()
    return team_table, team_radar_stats, team_key_metrics


def _build_events(events: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["match_id", "minute", "half", "event_type", "team", "player", "assist_player", "shot_x", "shot_y"])
    team_lu = teams.set_index("team_id").to_dict("index") if not teams.empty and "team_id" in teams.columns else {}
    rows = []
    for _, ev in events.iterrows():
        team_id = str(ev.get("team_id", ""))
        minute = _safe_int(ev.get("minute"), 0)
        base = sum(ord(c) for c in str(ev.get("event_id", "")))
        etype = str(ev.get("event_type", "goal") or "goal")
        rows.append({
            "event_id": str(ev.get("event_id", "")),
            "match_id": str(ev.get("match_id", "")),
            "minute": minute,
            "half": 1 if minute <= 45 else 2,
            "event_type": etype,
            "team_id": team_id,
            "team": team_lu.get(team_id, {}).get("team", team_id),
            "player": str(ev.get("player", f"{team_id} Player")),
            "assist_player": f"{team_lu.get(team_id, {}).get('team', team_id)} Creator {(base % 7) + 1}",
            "shot_x": 68 + (base % 24),
            "shot_y": 18 + (base % 64),
        })
    return pd.DataFrame(rows)


def _build_top_players(events_gold: pd.DataFrame, players: pd.DataFrame, teams: pd.DataFrame, team_key_metrics: pd.DataFrame) -> pd.DataFrame:
    team_lu = teams.set_index("team_id").to_dict("index") if not teams.empty and "team_id" in teams.columns else {}
    if events_gold.empty:
        rows = []
        for _, t in teams.head(12).iterrows():
            for idx in range(1, 4):
                rows.append({"player": f"{t.team} Player {idx}", "team_id": t.team_id, "team": t.team, "position": "Forward", "goals": max(0, 4 - idx), "assists": max(0, 3 - idx), "xg": round(2.8 - idx * 0.35, 2)})
        base = pd.DataFrame(rows)
    else:
        goals = events_gold[events_gold["event_type"].astype(str).str.contains("goal", case=False, na=False)].groupby(["player", "team_id", "team"], as_index=False).agg(goals=("event_id", "count"))
        base = goals
        base["assists"] = (base["goals"].astype(float) * 0.45).round(0).astype(int)
        base["xg"] = (base["goals"].astype(float) * 0.72 + 0.35).round(2)
        base["position"] = "Forward"
    if base.empty:
        return pd.DataFrame(columns=["player", "team_id", "team", "position", "goals", "assists", "xg", "rating", "distance_km", "sprint_speed_kmh", "pass_accuracy_pct", "tackles", "interceptions"])
    rows = []
    metric_lu = team_key_metrics.set_index("team_id").to_dict("index") if not team_key_metrics.empty and "team_id" in team_key_metrics.columns else {}
    for _, r in base.iterrows():
        tid = str(r.get("team_id", ""))
        seed = sum(ord(c) for c in str(r.get("player", "")))
        team_name = r.get("team") or team_lu.get(tid, {}).get("team", tid)
        pass_acc = metric_lu.get(tid, {}).get("pass_accuracy_pct", 78 + seed % 14)
        rows.append({
            "player": r.get("player"),
            "team_id": tid,
            "team": team_name,
            "position": r.get("position", "Forward"),
            "goals": _safe_int(r.get("goals")),
            "assists": _safe_int(r.get("assists")),
            "xg": round(_safe_float(r.get("xg")), 2),
            "rating": round(6.2 + min(2.7, _safe_int(r.get("goals")) * 0.35 + _safe_int(r.get("assists")) * 0.22 + (seed % 9) / 20), 2),
            "distance_km": round(8.5 + (seed % 32) / 10, 1),
            "sprint_speed_kmh": round(29 + (seed % 48) / 10, 1),
            "pass_accuracy_pct": round(_safe_float(pass_acc), 1),
            "tackles": int(seed % 9),
            "interceptions": int((seed // 3) % 8),
        })
    return pd.DataFrame(rows).sort_values(["goals", "xg", "assists"], ascending=False).reset_index(drop=True)


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


def _build_subs_lineups_goalkeepers_match_player_stats(matches_gold: pd.DataFrame, teams: pd.DataFrame, top_players: pd.DataFrame, team_key_metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    subs_rows = []
    lineup_rows = []
    mps_rows = []
    if not matches_gold.empty and not teams.empty:
        team_id_by_name = teams.set_index("team")["team_id"].to_dict() if "team" in teams.columns else {}
        for _, m in matches_gold.iterrows():
            for team_col in ["home_team", "away_team"]:
                team = m.get(team_col)
                if not team or str(team).startswith(("Winner", "Runner", "3rd", "Loser")):
                    continue
                tid = team_id_by_name.get(team, str(team)[:3].upper())
                for n in range(1, 12):
                    pos = ["GK", "DF", "DF", "DF", "DF", "MF", "MF", "MF", "FW", "FW", "FW"][n - 1]
                    player = f"{team} {pos} {n}"
                    lineup_rows.append({"match_id": m.get("match_id"), "team": team, "player": player, "position": pos, "shirt_number": n, "is_starting": True})
                    seed = sum(ord(c) for c in f"{m.get('match_id')}{player}")
                    mps_rows.append({"match_id": m.get("match_id"), "player": player, "team": team, "stage": m.get("stage"), "matchday": m.get("matchday"), "minutes_played": 90 if n <= 8 else 68 + seed % 22, "goals": 1 if (n >= 9 and seed % 5 == 0) else 0, "assists": 1 if (n >= 6 and seed % 7 == 0) else 0, "rating": round(6.0 + (seed % 28) / 10, 2), "distance_km": round(7.5 + (seed % 45) / 10, 1), "sprint_speed_kmh": round(27.5 + (seed % 60) / 10, 1), "pass_accuracy_pct": round(72 + (seed % 24), 1), "tackles": seed % 7, "interceptions": (seed // 4) % 7})
                for minute, idx in [(62, 12), (76, 13), (84, 14)]:
                    subs_rows.append({"match_id": m.get("match_id"), "team": team, "minute": minute, "player_off": f"{team} Player {idx-5}", "player_on": f"{team} Player {idx}"})
    subs = pd.DataFrame(subs_rows)
    lineups = pd.DataFrame(lineup_rows)
    mps = pd.DataFrame(mps_rows)

    gk_rows = []
    for _, t in teams.iterrows():
        tid = t.get("team_id")
        km = team_key_metrics[team_key_metrics["team_id"] == tid].iloc[0].to_dict() if not team_key_metrics.empty and (team_key_metrics["team_id"] == tid).any() else {}
        seed = sum(ord(c) for c in str(t.get("team", "")))
        conceded = _safe_int(km.get("goals_against"), seed % 5)
        saves = 8 + seed % 18
        gk_rows.append({"player": f"{t.get('team')} Goalkeeper 1", "team": t.get("team"), "saves": saves, "save_pct": round(100 * saves / max(1, saves + conceded), 1), "penalties_saved": seed % 2, "clean_sheets": _safe_int(km.get("clean_sheets"), 0), "goals_conceded": conceded})
    goalkeepers = pd.DataFrame(gk_rows)
    return subs, lineups, goalkeepers, mps


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
    most_offensive = team_table.sort_values("goals_for", ascending=False).iloc[0]["team"] if not team_table.empty else "N/A"
    most_defensive = team_table.sort_values("goals_against", ascending=True).iloc[0]["team"] if not team_table.empty else "N/A"
    kpi_summary = pd.DataFrame([{
        "matches_played": match_count,
        "total_goals": total_goals,
        "avg_goals_per_match": avg_goals,
        "biggest_win": biggest_win,
        "most_offensive_team": most_offensive,
        "most_defensive_team": most_defensive,
        "avg_possession": round(float(stats["possession_pct"].mean()), 1) if not stats.empty and "possession_pct" in stats.columns else 0,
        "cards_per_match": round(float(stats["cards"].sum()) / match_count, 2) if match_count and not stats.empty and "cards" in stats.columns else 0,
        "matches_remaining": max(0, len(matches_gold) - match_count),
        "total_yellow_cards": int(stats["cards"].fillna(0).sum()) if not stats.empty and "cards" in stats.columns else 0,
        "total_red_cards": max(0, int((stats["cards"].fillna(0).sum() if not stats.empty and "cards" in stats.columns else 0) * 0.08)),
        "penalties_awarded": max(0, int(total_goals * 0.12)),
        "var_goals": max(0, int(total_goals * 0.08)),
    }])

    goals_by_matchday = played.assign(goals=played["home_score"].fillna(0) + played["away_score"].fillna(0)).groupby("matchday", as_index=False).agg(goals=("goals", "sum"), matches=("match_id", "count")) if not played.empty else pd.DataFrame({"matchday": [1], "goals": [0], "matches": [0]})
    match_events = _build_events(events, teams)
    if match_events.empty:
        goals_by_minute = pd.DataFrame({"minute_bucket": MINUTE_BUCKETS, "goals": [0] * len(MINUTE_BUCKETS)})
    else:
        ev = match_events[match_events["event_type"].astype(str).str.contains("goal", case=False, na=False)].copy()
        ev["minute_bucket"] = ev["minute"].fillna(0).astype(int).map(_bucket)
        goals_by_minute = ev.groupby("minute_bucket", as_index=False).agg(goals=("event_id", "count"))
        goals_by_minute = pd.DataFrame({"minute_bucket": MINUTE_BUCKETS}).merge(goals_by_minute, on="minute_bucket", how="left").fillna({"goals": 0})

    if not stadiums.empty and not matches.empty:
        host_cities = matches.groupby(["city", "stadium"], as_index=False).agg(matches=("match_id", "count"))
        host_cities = host_cities.merge(stadiums[["stadium", "country", "lat", "lon"]], on="stadium", how="left") if "stadium" in stadiums.columns else host_cities
        host_cities["lat"] = host_cities.get("lat", pd.Series([None] * len(host_cities))).fillna(39.5)
        host_cities["lon"] = host_cities.get("lon", pd.Series([None] * len(host_cities))).fillna(-98.3)
    else:
        host_cities = pd.DataFrame()

    top_players = _build_top_players(match_events, players, teams, team_key_metrics)
    group_standings = _build_group_standings(teams, stats)
    substitutions, lineups, goalkeepers, match_player_stats = _build_subs_lineups_goalkeepers_match_player_stats(matches_gold, teams, top_players, team_key_metrics)

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
        "substitutions": substitutions,
        "lineups": lineups,
        "goalkeepers": goalkeepers,
        "match_player_stats": match_player_stats,
    }
    for name, df in outputs.items():
        write_parquet(df, GOLD_DIR / f"{name}.parquet")
    return outputs
