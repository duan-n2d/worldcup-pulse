# Lakehouse deployment guide

A free-tier, cloud-automated Data Engineering portfolio project for FIFA World Cup 2026.

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

- Cloud automation with GitHub Actions, triggered manually or by a token-protected Cloudflare Worker
- Full pull of every API endpoint on each run (no incremental watermark)
- Decoupled storage: code stays in GitHub, data lives in Hugging Face Dataset
- Bronze/Silver/Gold lakehouse layers
- Parquet data marts for fast DuckDB reads
- Data quality checks and pipeline audit logs
- Stateless Streamlit UI that pulls from the Dataset repo

## Updated marts for the expanded BI app

The `apps/overview/app.py` uses extra pages for Match Center, Group Standings, Player Leaderboard, and Venues. The ETL produces the related gold marts:

```text
gold/matches.parquet
gold/group_standings.parquet
gold/match_events.parquet
```

Lineups, substitutions, goalkeeper stats, and per-player ratings are not produced because the source API does not provide them. Stats the API omits are null; see `docs/hf-dataset-card.md`.

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
python -m pip install -r lakehouse/requirements.txt
cd lakehouse && python pipelines/run_pipeline.py --source worldcup26
# offline demo with the bundled sample payload (never uploaded):
cd lakehouse && python pipelines/run_pipeline.py --source worldcup26 --use-mock   # or WORLDCUP_USE_MOCK=1
```

If the API request fails, the run fails with a non-zero exit code. It does not fall back to mock data unless you pass `--use-mock`. Without `HF_TOKEN` and `HF_DATASET_REPO`, the pipeline still runs locally and writes to `data/`. With those variables set, it uploads the generated lakehouse data to the HF Dataset repo, except for mock runs, which are always refused.

## GitHub Actions secrets

- `HF_TOKEN`
- `HF_DATASET_REPO`

## Cloudflare Worker secrets

- `GITHUB_TOKEN`
- `GITHUB_REPO`
- `TRIGGER_TOKEN`: shared secret required on HTTP triggers (`wrangler secret put TRIGGER_TOKEN`)

## Deployment checklist

1. Create HF Dataset repo `worldcup-pulse-data`.
2. Push this repository to GitHub (the ETL lives in `lakehouse/`).
3. Add `HF_TOKEN` and `HF_DATASET_REPO` to GitHub Secrets.
4. Run the GitHub Actions `workflow_dispatch` once.
5. Deploy `apps/overview` and `apps/dataops` as two Hugging Face Spaces.
6. Set `HF_DATASET_REPO` and optionally `HF_TOKEN` in both Spaces.
7. Optionally deploy the Cloudflare Worker (`wrangler deploy`). Its cron is disabled (`crons = []`); trigger it with `curl -X POST -H "Authorization: Bearer $TRIGGER_TOKEN" https://<worker-url>/`.
8. Verify: dispatch -> ETL upload -> HF Dataset -> Spaces refresh within 300 seconds.
