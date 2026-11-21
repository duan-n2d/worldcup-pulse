from __future__ import annotations

import pandas as pd

from common import LOGS_DIR, SILVER_DIR, GOLD_DIR, iso_now, read_parquet


def _check(rows: list[dict], layer: str, table: str, check_name: str, passed: bool, message: str, severity: str = "Fail") -> None:
    # severity="Warn" is for tables that are legitimately empty when the source API omits that detail
    # (e.g. no goal-scorer lists); they are reported but do not fail the run.
    rows.append({"checked_at": iso_now(), "layer": layer, "table": table, "check_name": check_name, "status": "Pass" if passed else severity, "message": message})


# Only populated when the source payload carries goal/event details or stadium data.
OPTIONAL_SILVER = {"events", "players"}
OPTIONAL_GOLD = {"match_events", "top_players", "host_cities"}


def run_quality_checks() -> tuple[pd.DataFrame, bool]:
    rows: list[dict] = []
    teams = read_parquet(SILVER_DIR / "teams.parquet")
    matches = read_parquet(SILVER_DIR / "matches.parquet")
    stats = read_parquet(SILVER_DIR / "team_match_stats.parquet")
    events = read_parquet(SILVER_DIR / "events.parquet")
    players = read_parquet(SILVER_DIR / "players.parquet")
    valid_teams = set(teams["team_id"].astype(str)) if not teams.empty else set()
    _check(rows, "Silver", "teams", "not_empty", len(teams) > 0, f"rows={len(teams)}")
    _check(rows, "Silver", "teams", "unique_team_id", teams.empty or teams["team_id"].is_unique, f"duplicate_team_id={teams['team_id'].duplicated().sum() if not teams.empty else 0}")
    _check(rows, "Silver", "matches", "not_empty", len(matches) > 0, f"rows={len(matches)}")
    for table_name, df in [("team_match_stats", stats), ("events", events), ("players", players)]:
        _check(rows, "Silver", table_name, "not_empty", len(df) > 0, f"rows={len(df)}", "Warn" if table_name in OPTIONAL_SILVER else "Fail")
        missing = 0 if df.empty or "team_id" not in df.columns else (~df["team_id"].astype(str).isin(valid_teams)).sum()
        _check(rows, "Silver", table_name, "fk_team_id", missing == 0, f"missing_team_refs={int(missing)}")
    if not matches.empty and {"home_team_id", "away_team_id"}.issubset(matches.columns):
        both_known = matches["home_team_id"].astype(str).isin(valid_teams) & matches["away_team_id"].astype(str).isin(valid_teams)
        same = (both_known & matches["home_team_id"].astype(str).eq(matches["away_team_id"].astype(str))).sum()
        _check(rows, "Silver", "matches", "distinct_teams", same == 0, f"matches_with_same_home_and_away_team={int(same)}")
    if not teams.empty and "group_name" in teams.columns:
        unknown = teams["group_name"].astype(str).eq("Unknown").sum()
        _check(rows, "Silver", "teams", "group_known", unknown == 0, f"teams_without_group={int(unknown)}", "Warn")
    if not events.empty and not matches.empty and {"home_score", "away_score"}.issubset(matches.columns):
        goals = int(matches["home_score"].fillna(0).sum() + matches["away_score"].fillna(0).sum())
        # The source does not always name every scorer; report coverage rather than fail.
        _check(rows, "Silver", "events", "scorer_coverage", len(events) == goals,
               f"goal_events={len(events)} goals_from_scores={goals} missing={goals - len(events)}", "Warn")
    gold_tables = [
        "kpi_summary", "goals_by_matchday", "goals_by_minute_bucket", "host_cities",
        "team_radar_stats", "team_key_metrics", "top_players", "team_table",
        "matches", "group_standings", "match_events",
    ]
    for table in gold_tables:
        df = read_parquet(GOLD_DIR / f"{table}.parquet")
        _check(rows, "Gold", table, "not_empty", len(df) > 0, f"rows={len(df)}", "Warn" if table in OPTIONAL_GOLD else "Fail")
    gold_matches = read_parquet(GOLD_DIR / "matches.parquet")
    if not gold_matches.empty and "status" in gold_matches.columns:
        allowed = {"completed", "live", "scheduled"}
        bad_status = (~gold_matches["status"].astype(str).str.lower().isin(allowed)).sum()
        _check(rows, "Gold", "matches", "valid_status", bad_status == 0, f"bad_status_rows={int(bad_status)}")
    standings = read_parquet(GOLD_DIR / "group_standings.parquet")
    if not standings.empty and {"played", "group"}.issubset(standings.columns):
        # In a single round robin a team plays (group size - 1) group matches; more means
        # knockout matches leaked into the standings.
        limit = standings.groupby("group")["team"].transform("count") - 1
        over = (standings["played"] > limit).sum()
        _check(rows, "Gold", "group_standings", "group_stage_only", over == 0, f"teams_over_round_robin_limit={int(over)}")
    gold_events = read_parquet(GOLD_DIR / "match_events.parquet")
    if not gold_events.empty and "match_id" in gold_events.columns and not gold_matches.empty and "match_id" in gold_matches.columns:
        missing_match = (~gold_events["match_id"].astype(str).isin(set(gold_matches["match_id"].astype(str)))).sum()
        _check(rows, "Gold", "match_events", "fk_match_id", missing_match == 0, f"missing_match_refs={int(missing_match)}")
    report = pd.DataFrame(rows)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    report.to_csv(LOGS_DIR / "quality_checks.csv", index=False)
    passed = bool((report["status"] != "Fail").all())
    return report, passed
