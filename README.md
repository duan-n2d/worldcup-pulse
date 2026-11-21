# WorldCup Pulse

[![CI](https://github.com/duan-n2d/worldcup-pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/duan-n2d/worldcup-pulse/actions/workflows/ci.yml)

**Live:** [Overview app](https://huggingface.co/spaces/n2d/worldcup-pulse-overview) · [DataOps app](https://huggingface.co/spaces/n2d/worldcup-pulse-dataops) · [Dataset](https://huggingface.co/datasets/n2d/worldcup-pulse-data) (free Spaces sleep when idle; the first load takes about 30 s)

A free-tier, cloud-automated data platform for the FIFA World Cup 2026. A GitHub Actions ETL pulls the WorldCup26 API, builds a Bronze/Silver/Gold Parquet lakehouse, and publishes it to a Hugging Face Dataset as decoupled storage. Two stateless Streamlit apps read from that dataset: a public BI app and a DataOps monitor.

> **Status:** the tournament ended in July 2026. The scheduled refresh is disabled in both the GitHub workflow and the Cloudflare Worker (`crons = []`). You can still run the ETL from the Actions tab or through the token-protected Worker endpoint.

## Results

Measured on the published lakehouse (Bronze snapshot `772e610b`, 1 Aug 2026, after the final):

| | |
|---|---|
| Matches | 104 (72 group, 16 R32, 8 R16, 4 QF, 2 SF, 3rd place, final) |
| Teams / venues | 48 / 16 |
| Goals from scores | 308 (2.96 per match) |
| Goal events with a named scorer | 297 (5 penalties, 1 own goal); the source names no scorer for 11 goals |
| Quality checks | 25 pass, 1 warning (`events.scorer_coverage`) |

## Data provenance

The ETL ran every 30 minutes from 28 Jun 2026 (9,458 dataset commits up to 27 Aug). Two problems were found and fixed afterwards:

1. **Mock data was published.** From 1 Aug 2026 20:28 UTC the API stopped answering, and the original code silently fell back to its sample payload, so the public dataset showed 12 sample matches until now. The pipeline now fails on source errors, and the upload refuses mock runs.
2. **Silver did not match the real payload.** Team, stage, venue and scorer fields were read from key names the API never used, so stats were also filled in by generated values. Silver now reads the real schema (`home_team_id`, `name_en`, `type`, `local_date`, per-side scorer strings). Stats the API lacks stay null.

The API is now offline (`404`), so the public data was rebuilt with the current code from the last real Bronze snapshot by the [Replay from Bronze](.github/workflows/replay.yml) workflow ([`replay_from_hf.py`](lakehouse/pipelines/replay_from_hf.py)). The replay refuses any snapshot that does not contain all 104 matches.

## Architecture

```mermaid
flowchart LR
    CF[Cloudflare Worker<br/>token-protected trigger<br/>cron disabled] -->|repository_dispatch| GA[GitHub Actions<br/>full-pull ETL]
    API[(WorldCup26 API)] --> GA
    GA --> B[Bronze<br/>raw snapshots]
    B --> S[Silver<br/>canonical entities]
    S --> G[Gold<br/>11 BI marts]
    GA --> Q[Quality checks<br/>+ run logs]
    G --> HF[(Hugging Face Dataset<br/>single source of truth)]
    Q --> HF
    HF --> OV[Overview app<br/>BI · Streamlit]
    HF --> OPS[DataOps app<br/>monitoring · DuckDB console]
```

## Engineering highlights

- **Fully serverless, $0 to run**: Cloudflare Worker trigger, GitHub Actions compute, Hugging Face storage and hosting.
- **Simple full refresh**: every run pulls each API endpoint in full and rebuilds all layers. There is no incremental watermark; `state/last_run.json` only records the last successful run.
- **No invented numbers**: every stat comes from the API payload or is computed from it (scores, goal tallies, standings). Stats the API does not provide are published as null and shown as "N/A" or "Not available". This covers xG, shots, possession, pass accuracy, cards, set-piece goals, attendance, assists, and shot locations. Lineups, substitutions, goalkeeper stats, and player ratings are not published.
- **Fail loudly on source errors**: if the API is unreachable, the run fails with a non-zero exit. It does not swap in sample data. Mock data needs an explicit `--use-mock` flag and is never uploaded.
- **Decoupled storage** — the code repo never commits data; the HF Dataset repo is the only place lakehouse files live.
- **Medallion layers** in Parquet, read by DuckDB in the apps for fast, serverless queries.
- **Data quality and auditability** — per-run checks by layer/table (row counts, foreign keys, distinct home/away teams, group standings limited to the round robin, scorer coverage against scores) and a pipeline run log, surfaced in the DataOps app.
- **Stateless UIs** with a 5-minute cache. If the dataset cannot be read, the apps fall back to built-in sample data and show a prominent **MOCK DATA** banner.

## Repository layout

```text
lakehouse/
  pipelines/          ingest → bronze → silver → gold → quality checks → upload_to_hf
  cloud/              Cloudflare Worker that dispatches the ETL workflow (bearer-token protected, cron disabled)
  requirements.txt
apps/
  overview/           Public BI app: overview, match center, standings, teams, players, venues
  dataops/            Pipeline heartbeat, quality-check tabs, DuckDB console over gold marts
docs/
  lakehouse-deployment.md   End-to-end deployment checklist and secrets
  hf-dataset-card.md        Dataset card: lakehouse layout and every gold mart
.github/workflows/
  etl.yml             ETL job (dispatch / manual)
  replay.yml          Rebuild Silver/Gold from a published Bronze snapshot
  deploy-spaces.yml   Sync apps/ to the two Hugging Face Spaces
  ci.yml              Tests on every push
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r lakehouse/requirements.txt
cd lakehouse && python pipelines/run_pipeline.py --source worldcup26
```

Without `HF_TOKEN` and `HF_DATASET_REPO` the pipeline writes to `lakehouse/data/` only. If the WorldCup26 API is unavailable, the run exits non-zero. For an offline demo with the bundled sample payload, opt in explicitly:

```bash
cd lakehouse && python pipelines/run_pipeline.py --source worldcup26 --use-mock   # or WORLDCUP_USE_MOCK=1
```

The run manifest records mock runs (`used_mock: true`), and the upload step refuses to publish them to Hugging Face. `--mode` is accepted for compatibility and is only recorded; every run is a full pull.

Tests run the whole pipeline offline: the mock payload end to end, plus a fixture in the real API's shape (team-ID resolution, stages, venues, scorer-string parsing, own goals not credited to the player, standings from group matches only):

```bash
pip install pytest && cd lakehouse && python -m pytest -q tests
```

To run an app:

```bash
pip install -r apps/overview/requirements.txt
streamlit run apps/overview/app.py
```

## Deploy

See [docs/lakehouse-deployment.md](docs/lakehouse-deployment.md) for the full checklist: HF Dataset repo, GitHub secrets (`HF_TOKEN`, `HF_DATASET_REPO`), the two Spaces (`apps/overview`, `apps/dataops`), and the Cloudflare Worker secrets.

The Worker only dispatches the ETL for a `POST` request that carries a shared secret. Without the secret it returns `401`, and it returns `503` if the secret is not configured:

```bash
cd lakehouse/cloud/cloudflare-worker
wrangler secret put GITHUB_TOKEN     # token allowed to call repository_dispatch
wrangler secret put GITHUB_REPO      # owner/repo
wrangler secret put TRIGGER_TOKEN    # shared secret for HTTP triggers
wrangler deploy                      # crons = [] also removes any previously deployed cron

curl -X POST -H "Authorization: Bearer $TRIGGER_TOKEN" https://<your-worker>.workers.dev/
```

## Gold marts

Tournament KPIs, goals by matchday and minute bucket, host cities, team radar and key metrics, goal-scorer leaderboard, team table, matches, group standings, and match events. [docs/hf-dataset-card.md](docs/hf-dataset-card.md) has column-level descriptions and lists which columns are null when the source does not provide them.

## Honest limits

- The source has no xG, shots, possession, passing, cards, attendance, assists or line-ups, so those stay null.
- Some player names in the source are mangled transliterations (e.g. "Jvd Blingham"). They are published as received, not corrected by hand.
- Every run is a full refresh with no incremental watermark; at this data size that is cheaper than tracking state.
- The live Spaces run the code on `main`, synced by `deploy-spaces.yml`.

## Tech stack

Python · pandas · PyArrow · DuckDB · Streamlit · Plotly · GitHub Actions · Cloudflare Workers · Hugging Face Hub

## License

[MIT](LICENSE)
