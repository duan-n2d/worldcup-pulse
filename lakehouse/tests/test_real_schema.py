"""Silver/Gold on the WorldCup26 API's real payload shape (as stored in Bronze on the HF Dataset).

The fixture mirrors the real columns: teams carry name_en/groups/fifa_code, games carry
home_team_id/away_team_id, string scores, a `type` stage, a local_date and per-side
scorer strings such as {"K. Havertz 45'+5'(p)","D. Bobadilla 7'(OG)"}.
"""
import os
import subprocess
import sys
import textwrap

import pandas as pd
import pytest

from conftest import PIPELINES

sys.path.insert(0, str(PIPELINES))


@pytest.fixture(scope="module")
def real_shape_run(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("real_shape")
    bronze = data_dir / "bronze"
    bronze.mkdir()
    pd.DataFrame([
        {"id": "1", "name_en": "Mexico", "fifa_code": "MEX", "iso2": "MX", "groups": "A", "flag": "mx.png"},
        {"id": "2", "name_en": "South Africa", "fifa_code": "RSA", "iso2": "ZA", "groups": "A", "flag": "za.png"},
        {"id": "3", "name_en": "Germany", "fifa_code": "GER", "iso2": "DE", "groups": "E", "flag": "de.png"},
        {"id": "4", "name_en": "Paraguay", "fifa_code": "PAR", "iso2": "PY", "groups": "E", "flag": "py.png"},
    ]).to_parquet(bronze / "teams.parquet")
    pd.DataFrame([
        {"id": "7", "name_en": "Estadio Azteca", "city_en": "Mexico City", "country_en": "Mexico"},
    ]).to_parquet(bronze / "stadiums.parquet")
    pd.DataFrame([
        {"id": "1", "home_team_id": "1", "away_team_id": "2", "home_score": "2", "away_score": "0",
         "home_scorers": '{“J. Quiñones 9\'”,”R. Jiménez 67\'”}', "away_scorers": "null",
         "type": "group", "matchday": "1", "local_date": "06/11/2026 13:00", "stadium_id": "7",
         "finished": "TRUE", "time_elapsed": "finished", "home_team_label": None, "away_team_label": None},
        {"id": "2", "home_team_id": "3", "away_team_id": "4", "home_score": "2", "away_score": "1",
         "home_scorers": '{"K. Havertz 45\'+5\'(p)","D. Bobadilla 7\'(OG)"}', "away_scorers": '{"M. Almirón 80\'"}',
         "type": "group", "matchday": "1", "local_date": "06/12/2026 16:00", "stadium_id": "7",
         "finished": "TRUE", "time_elapsed": "finished", "home_team_label": None, "away_team_label": None},
        {"id": "3", "home_team_id": "1", "away_team_id": "3", "home_score": "1", "away_score": "1",
         "home_scorers": '{"R. Jiménez 30\'"}', "away_scorers": '{"J. Musiala 88\'"}',
         "type": "r32", "matchday": "4", "local_date": "06/29/2026 19:00", "stadium_id": "7",
         "finished": "TRUE", "time_elapsed": "finished", "home_team_label": "Winner Group A",
         "away_team_label": "Winner Group E", "home_penalty_score": "4", "away_penalty_score": "3"},
    ]).to_parquet(bronze / "games.parquet")

    script = textwrap.dedent("""
        from silver import build_silver
        from gold import build_gold
        from quality_checks import run_quality_checks
        build_silver(); build_gold()
        report, passed = run_quality_checks()
        report.to_csv(r"{out}", index=False)
        raise SystemExit(0 if passed else 3)
    """).format(out=data_dir / "qc.csv")
    proc = subprocess.run([sys.executable, "-c", script], cwd=PIPELINES, capture_output=True, text=True,
                          env={**os.environ, "DATA_DIR": str(data_dir)}, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    read = lambda layer, name: pd.read_parquet(data_dir / layer / f"{name}.parquet")  # noqa: E731
    return {"read": read, "qc": pd.read_csv(data_dir / "qc.csv")}


def test_teams_resolve_from_source_ids(real_shape_run):
    m = real_shape_run["read"]("gold", "matches").set_index("match_id")
    assert m.loc["1", ["home_team", "away_team"]].tolist() == ["Mexico", "South Africa"]
    assert m.loc["3", ["home_team", "away_team"]].tolist() == ["Mexico", "Germany"]
    assert (m["home_team"] != m["away_team"]).all()


def test_stage_venue_kickoff_and_penalties(real_shape_run):
    m = real_shape_run["read"]("gold", "matches").set_index("match_id")
    assert m.loc["1", "stage"] == "Group" and m.loc["1", "group"] == "A"
    assert m.loc["3", "stage"] == "R32" and m.loc["3", "group"] is None
    assert m.loc["1", ["venue", "city"]].tolist() == ["Estadio Azteca", "Mexico City"]
    assert m.loc["1", ["match_date", "kickoff_local"]].tolist() == ["2026-06-11", "13:00"]
    assert m.loc["3", ["home_penalty_score", "away_penalty_score"]].tolist() == [4, 3]
    assert set(m["status"]) == {"completed"}


def test_scorer_strings_become_goal_events(real_shape_run):
    ev = real_shape_run["read"]("silver", "events")
    assert len(ev) == 7  # every listed scorer, including the curly-quoted ones
    assert ev["event_type"].value_counts().to_dict() == {"goal": 5, "penalty_goal": 1, "own_goal": 1}


def test_own_goal_is_not_credited_to_the_player(real_shape_run):
    top = real_shape_run["read"]("gold", "top_players")
    assert "D. Bobadilla" not in set(top["player"])
    assert top.set_index("player").loc["R. Jiménez", "goals"] == 2
    kpi = real_shape_run["read"]("gold", "kpi_summary").iloc[0]
    assert kpi["own_goals"] == 1 and kpi["penalty_goals"] == 1
    assert pd.isna(kpi["penalties_awarded"])  # misses are not in the source, so "awarded" is unknown


def test_standings_count_group_matches_only(real_shape_run):
    st = real_shape_run["read"]("gold", "group_standings").set_index("team")
    assert st.loc["Mexico", "played"] == 1 and st.loc["Mexico", "points"] == 3
    assert st.loc["Mexico", "qualification_status"] == "qualified"
    assert st.loc["South Africa", "qualification_status"] == "eliminated"


def test_quality_checks_pass_with_full_scorer_coverage(real_shape_run):
    qc = real_shape_run["qc"].set_index("check_name")
    assert qc.loc["distinct_teams", "status"] == "Pass"
    assert qc.loc["scorer_coverage", "status"] == "Pass"
    assert qc.loc["group_stage_only", "status"] == "Pass"


@pytest.mark.parametrize("raw, expected", [
    ("null", []),
    ('{"Maurício 73\'"}', [("Maurício", 73, None, "goal")]),
    ('{"K. Havertz 45\'+5\'(p)"}', [("K. Havertz", 45, 5, "penalty_goal")]),
    ('{"P. Musa 45+5\'"}', [("P. Musa", 45, 5, "goal")]),
    ('{"Youri Tielemans 125(P)\'"}', [("Youri Tielemans", 125, None, "penalty_goal")]),
    ('{"Breel Embolo 17\' (p)"}', [("Breel Embolo", 17, None, "penalty_goal")]),
    ('{"D. Bobadilla 7\'(OG)"}', [("D. Bobadilla", 7, None, "own_goal")]),
])
def test_parse_scorers(raw, expected):
    os.environ.setdefault("DATA_DIR", str(PIPELINES.parent / ".pytest-data"))
    from silver import parse_scorers
    got = [(e["player"], e["minute"], e["added_time"], e["event_type"]) for e in parse_scorers(raw)]
    assert got == expected
