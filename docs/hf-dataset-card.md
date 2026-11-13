# WorldCup Pulse Data

This Hugging Face Dataset repository is the **single source of truth** for WorldCup Pulse Lakehouse data. The GitHub code repo never commits generated data; GitHub Actions uploads this lakehouse output to this dataset repo.

## Lakehouse layout

```text
bronze/*.parquet     # normalized raw API snapshots
silver/*.parquet     # cleaned canonical entities and events
gold/*.parquet       # dashboard-ready marts
state/last_run.json  # incremental state
logs/*.csv           # pipeline and quality audit logs
```

## Gold marts

Core tournament marts:

- `kpi_summary.parquet`: tournament-level KPIs including matches played, goals, avg goals, biggest win, cards, penalties, VAR goals, and matches remaining.
- `goals_by_matchday.parquet`: goals and match counts by matchday.
- `goals_by_minute_bucket.parquet`: goal distribution across 15-minute buckets.
- `host_cities.parquet`: stadium, city, country, coordinates, and hosted match count.
- `team_radar_stats.parquet`: attack, defense, possession, passing, and discipline score by team.
- `team_key_metrics.parquet`: xG, shots/match, possession, pass accuracy, goals for/against, cards, clean sheets, and set-piece goals.
- `top_players.parquet`: player attacking and contribution leaderboard.
- `team_table.parquet`: team-level aggregate table.

Expanded BI marts used by the updated Overview Space:

- `matches.parquet`: fixture/result table with match IDs, teams, flags, scores, xG, venue, city, status, and kickoff metadata.
- `group_standings.parquet`: live group table with played, W-D-L, goals for/against, goal difference, points, and qualification status.
- `match_events.parquet`: goal/card-style events with minute, half, team, player, assist player, and pitch coordinates.
- `substitutions.parquet`: substitution timing and player changes by match.
- `lineups.parquet`: starting XI-style lineup rows by match and team.
- `goalkeepers.parquet`: goalkeeper saves, save percentage, penalties saved, clean sheets, and goals conceded.
- `match_player_stats.parquet`: per-player-per-match form, ratings, distance, speed, passing, tackles, and interceptions.

## Operational logs

- `logs/pipeline_runs.csv`: run ID, start/end timestamp, status, row counts, and error message.
- `logs/quality_checks.csv`: quality checks by layer/table/check name/status.
