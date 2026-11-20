---
title: WorldCup Pulse DataOps
emoji: ⚙️
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: 1.41.1
app_file: app.py
pinned: false
---

# WorldCup Pulse DataOps

Technical monitoring Streamlit Space for WorldCup Pulse Lakehouse.

## Features

- Pipeline heartbeat from `logs/pipeline_runs.csv`
- Data quality tabs from `logs/quality_checks.csv`
- DuckDB console over all gold marts, including the match, group-standings, and match-event marts
- Last sync indicator (the scheduled refresh is disabled, so the next run shows as "Manual only")
- A "MOCK DATA" banner whenever logs or marts fall back to built-in sample data because the HF Dataset could not be read

## Required Space secrets

- `HF_DATASET_REPO`: e.g. `your-username/worldcup-pulse-data`
- `HF_TOKEN`: only needed if the Dataset repo is private
