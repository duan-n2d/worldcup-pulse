"""End-to-end and guard tests for the WorldCup Pulse lakehouse, run on the mock payload."""
import json
import os
import subprocess
import sys

import pandas as pd

from conftest import PIPELINES

EXPECTED_MARTS = {
    "goals_by_matchday", "goals_by_minute_bucket", "group_standings", "host_cities",
    "kpi_summary", "match_events", "matches", "team_key_metrics", "team_radar_stats",
    "team_table", "top_players",
}
RETIRED_SYNTHETIC_MARTS = {"lineups", "substitutions", "goalkeepers", "match_player_stats"}

# Stats the WorldCup26 API does not provide. They must stay null rather than be invented.
NOT_IN_SOURCE = {
    "matches": ["home_xg", "away_xg", "attendance"],
    "team_key_metrics": ["xg", "shots_per_match", "possession_pct", "pass_accuracy_pct", "setpiece_goals"],
    "team_table": ["xg", "shots", "possession_pct", "pass_accuracy_pct"],
    "match_events": ["assist_player", "shot_x", "shot_y"],
}


def test_pipeline_builds_every_gold_mart(mock_run):
    assert set(mock_run["gold"]) == EXPECTED_MARTS
    assert all(len(df) > 0 for df in mock_run["gold"].values())


def test_retired_synthetic_marts_are_not_produced(mock_run):
    assert not RETIRED_SYNTHETIC_MARTS & set(mock_run["gold"])


def test_stats_missing_from_source_are_null_not_fabricated(mock_run):
    for mart, cols in NOT_IN_SOURCE.items():
        df = mock_run["gold"][mart]
        for col in cols:
            assert df[col].isna().all(), f"{mart}.{col} has values the source never provided"


def test_goal_totals_reconcile_between_matches_and_events(mock_run):
    gold = mock_run["gold"]
    matches = gold["matches"]
    score_cols = [c for c in ("home_score", "away_score") if c in matches.columns]
    assert len(score_cols) == 2, matches.columns.tolist()
    goals_from_scores = int(matches[score_cols].fillna(0).sum().sum())
    goals_from_events = int((gold["match_events"]["event_type"].str.lower().str.contains("goal")).sum())
    assert goals_from_events <= goals_from_scores


def test_quality_checks_pass_and_run_is_logged(mock_run):
    report = pd.read_csv(next((mock_run["data_dir"] / "logs").glob("*quality*.csv")))
    assert not report["status"].eq("Fail").any()
    runs = pd.read_csv(mock_run["data_dir"] / "logs" / "pipeline_runs.csv")
    assert runs.iloc[-1]["status"] == "SuccessLocalNoUpload"


def test_mock_data_is_never_uploaded(mock_run):
    runs = pd.read_csv(mock_run["data_dir"] / "logs" / "pipeline_runs.csv")
    assert runs.iloc[-1]["error_message"] == "REFUSED_MOCK_DATA_NOT_UPLOADED"
    state = json.loads((mock_run["data_dir"] / "state" / "last_run.json").read_text())
    assert state["used_mock"] is True


def test_upload_refuses_mock_even_with_credentials(tmp_path):
    code = (
        "from upload_to_hf import upload_data_to_hf;"
        "print(upload_data_to_hf('someone/some-dataset', 'fake-token', used_mock=True))"
    )
    env = {**os.environ, "DATA_DIR": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", code], cwd=PIPELINES, env=env,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out == "REFUSED_MOCK_DATA_NOT_UPLOADED"
