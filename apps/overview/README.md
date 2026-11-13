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

The app has mock fallback data for every table used by the UI, so the Space can demo immediately before the first ETL run lands data in the HF Dataset.

## Required Space secrets

- `HF_DATASET_REPO`: e.g. `your-username/worldcup-pulse-data`
- `HF_TOKEN`: only needed if the Dataset repo is private
- `GITHUB_REPO`: optional, enables the Trigger ETL button
- `GITHUB_TOKEN`: optional, enables the Trigger ETL button
