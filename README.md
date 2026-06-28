# WorldCup Pulse Lakehouse

A free-tier, cloud-automated, near-real-time Data Engineering portfolio project for FIFA World Cup 2026.

## Architecture

```text
WorldCup26 API
  -> GitHub Actions ETL
  -> Bronze / Silver / Gold parquet lakehouse
  -> Hugging Face Dataset repo as decoupled storage
  -> Two Hugging Face Spaces
      - worldcup-pulse-overview
      - worldcup-pulse-dataops
```

## Why this is a Data Engineering project

- Cloud automation with Cloudflare Worker cron and GitHub Actions
- Incremental pipeline mode
- Decoupled storage: code stays in GitHub, data lives in Hugging Face Dataset
- Bronze/Silver/Gold lakehouse layers
- Parquet data marts for fast DuckDB reads
- Data quality checks and pipeline audit logs
- Stateless Streamlit UI that pulls from the Dataset repo

## Updated marts for the expanded BI app

The updated `worldcup-pulse-overview/app.py` uses extra pages for Match Center, Group Standings, Player Leaderboard, and Venues. The ETL now produces the related gold marts:

```text
gold/matches.parquet
gold/group_standings.parquet
gold/match_events.parquet
gold/substitutions.parquet
gold/lineups.parquet
gold/goalkeepers.parquet
gold/match_player_stats.parquet
```

The original marts are still produced:

```text
gold/kpi_summary.parquet
gold/goals_by_matchday.parquet
gold/goals_by_minute_bucket.parquet
gold/host_cities.parquet
gold/team_radar_stats.parquet
gold/team_key_metrics.parquet
gold/top_players.parquet
gold/team_table.parquet
```

## Local run

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows PowerShell after Set-ExecutionPolicy -Scope Process RemoteSigned
python -m pip install -r requirements.txt
python pipelines/run_pipeline.py --source worldcup26 --mode incremental
```

Without `HF_TOKEN` and `HF_DATASET_REPO`, the pipeline still runs locally and writes to `data/`. With those variables set, it uploads the generated lakehouse data to the HF Dataset repo.

## GitHub Actions secrets

- `HF_TOKEN`
- `HF_DATASET_REPO`

## Cloudflare Worker secrets

- `GITHUB_TOKEN`
- `GITHUB_REPO`

## Deployment checklist

1. Create HF Dataset repo `worldcup-pulse-data`.
2. Push this folder to GitHub repo `worldcup-pulse-lakehouse`.
3. Add `HF_TOKEN` and `HF_DATASET_REPO` to GitHub Secrets.
4. Run the GitHub Actions `workflow_dispatch` once.
5. Deploy `worldcup-pulse-overview` and `worldcup-pulse-dataops` as two Hugging Face Spaces.
6. Set `HF_DATASET_REPO` and optionally `HF_TOKEN` in both Spaces.
7. Deploy the Cloudflare Worker cron.
8. Verify: Cloudflare cron -> GitHub dispatch -> ETL upload -> HF Dataset -> Spaces refresh within 300 seconds.
