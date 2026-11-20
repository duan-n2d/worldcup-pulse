---
title: WorldCup Pulse Overview
emoji: ⚽
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: 1.41.1
app_file: app.py
pinned: false
---

# WorldCup Pulse Overview

Public Streamlit BI Space for the WorldCup Pulse Lakehouse.

This app is stateless. It reads the latest gold marts from the Hugging Face Dataset repo configured by `HF_DATASET_REPO`, with `st.cache_data(ttl=300)` to keep the public UI responsive.

## Pages

- ⚽ Overview
- 🏟️ Match Center
- 🏆 Group Standings
- 📊 Team Intelligence
- 🥇 Player Leaderboard
- 🌆 Venues & Cities

If the HF Dataset cannot be read, the app falls back to built-in mock data so the Space still renders. Whenever that happens, a **"MOCK DATA — not real tournament results"** banner names the affected tables. Stats the source API does not provide (for example xG, possession, cards, lineups, and goalkeeper stats) show as "N/A" or a "Not available" note. They are never estimated.

## Required Space secrets

- `HF_DATASET_REPO`: e.g. `your-username/worldcup-pulse-data`
- `HF_TOKEN`: only needed if the Dataset repo is private (use a read-only token)

The Space never holds a GitHub token. To refresh data, trigger the ETL from GitHub Actions (`workflow_dispatch`) or via the token-protected Cloudflare Worker.
