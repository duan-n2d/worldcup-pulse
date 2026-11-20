# WorldCup Pulse Data

This Hugging Face Dataset repository is the **single source of truth** for WorldCup Pulse Lakehouse data. The GitHub code repo never commits generated data; GitHub Actions uploads this lakehouse output to this dataset repo.

## Lakehouse layout

```text
bronze/*.parquet     # normalized raw API snapshots
silver/*.parquet     # cleaned canonical entities and events
gold/*.parquet       # dashboard-ready marts
state/last_run.json  # last successful run metadata (every run is a full pull)
logs/*.csv           # pipeline and quality audit logs
```

## Data provenance

Every value comes from the WorldCup26 API payload or is computed from it (scores, goal tallies, standings). Nothing is estimated. Stats the API does not provide are **null**, not filled in: xG, shots, possession, pass accuracy, cards, set-piece goals, attendance, assists, player positions, shot coordinates, and card/penalty/VAR counts. If a later payload carries one of these fields, the pipeline picks it up.

Offline demo runs (`--use-mock`) use a bundled sample payload. They are never uploaded here.

## Gold marts

Core tournament marts:

- `kpi_summary.parquet`: tournament-level KPIs: matches played, goals, avg goals, biggest win, most offensive/defensive team, and matches remaining. Possession, cards, penalties, and VAR goals are null unless the source reports them.
- `goals_by_matchday.parquet`: goals and match counts by matchday.
- `goals_by_minute_bucket.parquet`: goal distribution across 15-minute buckets.
- `host_cities.parquet`: stadium, city, country, coordinates (null if not in the source), and hosted match count.
- `team_radar_stats.parquet`: attack and defense indices derived from goals for/against; possession, passing, and discipline are null unless the source reports them.
- `team_key_metrics.parquet`: goals for/against and clean sheets. xG, shots/match, possession, pass accuracy, cards, and set-piece goals are null unless the source reports them.
- `top_players.parquet`: goal-scorer leaderboard from source goal events. Assists and position are filled only when the source names them.
- `team_table.parquet`: team-level aggregate table.

Expanded BI marts used by the Overview Space:

- `matches.parquet`: fixture/result table with match IDs, teams, flags, scores, venue, city, status, and kickoff metadata. xG, attendance, and kickoff date/time are null when the source omits them.
- `group_standings.parquet`: group table with played, W-D-L, goals for/against, goal difference, points, and a points-based qualification status. The status is a heuristic, not official FIFA tie-breaking.
- `match_events.parquet`: events from the source goal lists, with minute, half, team, player, and assist player when provided. `shot_x`/`shot_y` are always null because the source has no shot locations.

Earlier versions also published `substitutions`, `lineups`, `goalkeepers`, and `match_player_stats`. Their values were synthetic, so those marts were removed. The upload deletes stale `gold/*.parquet` files.

## Operational logs

- `logs/pipeline_runs.csv`: run ID, start/end timestamp, status, row counts, and error message.
- `logs/quality_checks.csv`: quality checks by layer/table/check name/status.
