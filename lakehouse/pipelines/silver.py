from __future__ import annotations

from typing import Any

import pandas as pd

from common import BRONZE_DIR, SILVER_DIR, canonical_id, clean_text, first_present, is_placeholder_team, read_parquet, write_parquet

FLAG_MAP = {
    "CAN": "🇨🇦", "MEX": "🇲🇽", "USA": "🇺🇸", "BRA": "🇧🇷", "FRA": "🇫🇷", "ARG": "🇦🇷", "ENG": "🏴", "ESP": "🇪🇸",
    "GER": "🇩🇪", "POR": "🇵🇹", "ITA": "🇮🇹", "NED": "🇳🇱", "URU": "🇺🇾", "JPN": "🇯🇵", "KOR": "🇰🇷", "AUS": "🇦🇺",
}


def _row_get(row: pd.Series, keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, (list, dict, tuple)) or hasattr(value, "tolist"):
            return value
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        if value != "":
            return value
    return default


def _load_bronze() -> dict[str, pd.DataFrame]:
    return {p.stem: read_parquet(p) for p in BRONZE_DIR.glob("*.parquet")}


def _team_aliases(teams: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    out = []
    alias: dict[str, str] = {}
    for _, row in teams.iterrows():
        raw_id = _row_get(row, ["id", "team_id", "country_id"])
        name = clean_text(_row_get(row, ["name", "team", "country", "country_name"], "Unknown"))
        code = clean_text(_row_get(row, ["fifa_code", "code", "abbreviation", "iso2", "iso3"], ""))
        if not code or len(code) < 2:
            code = canonical_id(name)[:3]
        team_id = canonical_id(code)
        if is_placeholder_team(name) or is_placeholder_team(team_id):
            continue
        group_name = clean_text(_row_get(row, ["group", "group_name", "group_group_name"], "Unknown"))
        fifa_rank = _row_get(row, ["rank", "fifa_rank", "ranking"], 999)
        try:
            fifa_rank = int(float(fifa_rank))
        except Exception:
            fifa_rank = 999
        flag = clean_text(_row_get(row, ["flag", "emoji"], FLAG_MAP.get(team_id, "🏳️")))
        out.append({
            "team_id": team_id,
            "team": name,
            "source_team_id": clean_text(raw_id),
            "group_name": group_name,
            "fifa_rank": fifa_rank,
            "flag": flag,
            "confederation": clean_text(_row_get(row, ["confederation"], "Unknown")),
        })
        for key in [raw_id, name, code, team_id, canonical_id(name)]:
            if clean_text(key):
                alias[canonical_id(key)] = team_id
    df = pd.DataFrame(out).drop_duplicates("team_id") if out else pd.DataFrame(columns=["team_id","team","source_team_id","group_name","fifa_rank","flag","confederation"])
    return df, alias


def _resolve_team(value: Any, alias: dict[str, str]) -> str:
    key = canonical_id(value)
    return alias.get(key, key)


def _stadiums(stadiums: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in stadiums.iterrows():
        name = clean_text(_row_get(row, ["name", "stadium", "venue"], "Unknown Stadium"))
        rows.append({
            "stadium_id": canonical_id(_row_get(row, ["id", "stadium_id", "name"], name)),
            "stadium": name,
            "city": clean_text(_row_get(row, ["city", "location_city"], "Unknown")),
            "country": clean_text(_row_get(row, ["country", "location_country"], "Unknown")),
            "lat": pd.to_numeric(pd.Series([_row_get(row, ["lat", "latitude", "location_lat"], None)]), errors="coerce").iloc[0],
            "lon": pd.to_numeric(pd.Series([_row_get(row, ["lon", "lng", "longitude", "location_lon"], None)]), errors="coerce").iloc[0],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        # No stadiums in the source payload: publish an empty table rather than invented venues.
        return pd.DataFrame(columns=["stadium_id", "stadium", "city", "country", "lat", "lon"])
    return df.drop_duplicates("stadium_id")


def _extract_score(row: pd.Series, keys: list[str]) -> int | None:
    value = _row_get(row, keys, None)
    try:
        if pd.isna(value):
            return None
        return int(float(value))
    except Exception:
        return None


# Per-team match stats are only kept when the source payload carries them
# (e.g. ``home_xg`` / ``away_possession``). Nothing is derived or invented:
# a stat the API does not provide stays null.
SIDE_STATS = {
    "xg": ["xg", "expected_goals"],
    "shots": ["shots", "total_shots"],
    "possession_pct": ["possession", "possession_pct", "ball_possession"],
    "pass_accuracy_pct": ["pass_accuracy", "pass_accuracy_pct", "passes_accuracy"],
    "cards": ["cards"],
}


def _side_stat(row: pd.Series, side: str, names: list[str]) -> float | None:
    keys = [f"{side}_{n}" for n in names] + [f"{side}Team_{n}" for n in names] + [f"stats_{side}_{n}" for n in names]
    value = pd.to_numeric(pd.Series([_row_get(row, keys, None)]), errors="coerce").iloc[0]
    return None if pd.isna(value) else float(value)


def build_silver() -> dict[str, pd.DataFrame]:
    bronze = _load_bronze()
    teams_df, alias = _team_aliases(bronze.get("teams", pd.DataFrame()))
    stadiums_df = _stadiums(bronze.get("stadiums", pd.DataFrame()))
    games = bronze.get("games", pd.DataFrame())

    matches = []
    slots = []
    stats_rows = []
    events = []
    players = []
    valid_team_ids = set(teams_df["team_id"].astype(str))
    for _, row in games.iterrows():
        match_id = canonical_id(_row_get(row, ["id", "match_id", "game_id", "match_number"], len(matches)+1))
        matchday = _row_get(row, ["matchday", "day", "round", "match_number"], 1)
        try: matchday = int(float(matchday))
        except Exception: matchday = 1
        stage = clean_text(_row_get(row, ["stage", "round", "phase"], "Unknown"))
        home_raw = _row_get(row, ["home_team", "home", "team1", "home_name", "homeTeam_name", "home_team_name"], "")
        away_raw = _row_get(row, ["away_team", "away", "team2", "away_name", "awayTeam_name", "away_team_name"], "")
        home_id = _resolve_team(home_raw, alias)
        away_id = _resolve_team(away_raw, alias)
        for val, tid in [(home_raw, home_id), (away_raw, away_id)]:
            if is_placeholder_team(val) or is_placeholder_team(tid):
                slots.append({"slot_id": tid, "slot_label": clean_text(val), "stage": stage, "match_id": match_id})
        home_score = _extract_score(row, ["home_score", "home_goals", "score_home", "homeTeam_score"])
        away_score = _extract_score(row, ["away_score", "away_goals", "score_away", "awayTeam_score"])
        status = clean_text(_row_get(row, ["status", "state"], "scheduled")) or "scheduled"
        city = clean_text(_row_get(row, ["city", "venue_city"], "Unknown"))
        stadium = clean_text(_row_get(row, ["stadium", "venue", "stadium_name"], "Unknown Stadium"))
        attendance = pd.to_numeric(pd.Series([_row_get(row, ["attendance", "spectators"], None)]), errors="coerce").iloc[0]
        matches.append({
            "match_id": match_id,
            "match_number": _row_get(row, ["match_number", "id"], match_id),
            "matchday": matchday,
            "stage": stage,
            "status": status,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_team_label": clean_text(home_raw),
            "away_team_label": clean_text(away_raw),
            "home_score": home_score,
            "away_score": away_score,
            "stadium": stadium,
            "city": city,
            "kickoff_utc": clean_text(_row_get(row, ["date", "datetime", "kickoff", "time"], "")),
            "attendance": None if pd.isna(attendance) else int(attendance),
        })
        if home_id in valid_team_ids and away_id in valid_team_ids and home_score is not None and away_score is not None:
            for side, team_id, goals_for, goals_against in [("home", home_id, home_score, away_score), ("away", away_id, away_score, home_score)]:
                stats_rows.append({
                    "match_id": match_id,
                    "team_id": team_id,
                    "goals_for": goals_for,
                    "goals_against": goals_against,
                    **{stat: _side_stat(row, side, names) for stat, names in SIDE_STATS.items()},
                })
        # Events only come from the source's goal/event list; none are synthesized from the score.
        goal_list = _row_get(row, ["goals", "scorers", "events"], None)
        if hasattr(goal_list, "tolist") and not isinstance(goal_list, list):
            goal_list = goal_list.tolist()
        if not isinstance(goal_list, list):
            goal_list = []
        for i, ev in enumerate(goal_list):
            if not isinstance(ev, dict):
                continue
            team_raw = first_present(ev, ["team", "team_name", "team_id"], None)
            if team_raw is None:
                continue
            team_id = _resolve_team(team_raw, alias)
            if team_id not in valid_team_ids:
                continue
            minute = first_present(ev, ["minute", "time", "elapsed"], None)
            try: minute = int(float(minute))
            except Exception: minute = None
            player = clean_text(first_present(ev, ["player", "player_name", "scorer"], ""))
            assist = clean_text(first_present(ev, ["assist", "assist_player", "assist_name"], ""))
            event_type = clean_text(first_present(ev, ["type", "event_type", "kind"], "goal")).lower() or "goal"
            events.append({"event_id": f"{match_id}_{i+1}", "match_id": match_id, "team_id": team_id, "player": player or None, "assist_player": assist or None, "event_type": event_type, "minute": minute})
            if player:
                position = clean_text(first_present(ev, ["position", "player_position"], ""))
                players.append({"player_id": canonical_id(f"{team_id}_{player}"), "player": player, "team_id": team_id, "position": position or None})
    matches_df = pd.DataFrame(matches)
    slots_df = pd.DataFrame(slots).drop_duplicates("slot_id") if slots else pd.DataFrame(columns=["slot_id","slot_label","stage","match_id"])
    stats_df = pd.DataFrame(stats_rows) if stats_rows else pd.DataFrame(columns=["match_id", "team_id", "goals_for", "goals_against", *SIDE_STATS])
    events_df = pd.DataFrame(events) if events else pd.DataFrame(columns=["event_id", "match_id", "team_id", "player", "assist_player", "event_type", "minute"])
    players_df = pd.DataFrame(players).drop_duplicates("player_id") if players else pd.DataFrame(columns=["player_id","player","team_id","position"])
    outputs = {"teams": teams_df, "stadiums": stadiums_df, "matches": matches_df, "fixture_slots": slots_df, "team_match_stats": stats_df, "events": events_df, "players": players_df}
    for name, df in outputs.items():
        write_parquet(df, SILVER_DIR / f"{name}.parquet")
    return outputs
