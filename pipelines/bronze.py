from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from common import BRONZE_DIR, RAW_DIR, compact_ts, write_parquet


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x if isinstance(x, dict) else {"value": x} for x in payload]
    if isinstance(payload, dict):
        for key in ["data", "items", "result", "results", "teams", "games", "stadiums", "groups"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [x if isinstance(x, dict) else {"value": x} for x in value]
        return [payload]
    return []


def _latest_raw_snapshot() -> Path:
    snapshots = sorted(RAW_DIR.glob("worldcup26_*"), reverse=True)
    if not snapshots:
        raise FileNotFoundError("No raw snapshot found under data/raw")
    return snapshots[0]


def build_bronze(raw_paths: dict[str, Path] | None = None) -> dict[str, pd.DataFrame]:
    if raw_paths is None:
        snap = _latest_raw_snapshot()
        raw_paths = {p.stem: p for p in snap.glob("*.json") if p.name != "manifest.json"}
    run_ts = compact_ts()
    result: dict[str, pd.DataFrame] = {}
    for table, path in raw_paths.items():
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = _records(payload)
        df = pd.json_normalize(rows, sep="_") if rows else pd.DataFrame()
        df["_bronze_loaded_at"] = run_ts
        df["_source_file"] = str(path)
        result[table] = df
        write_parquet(df, BRONZE_DIR / f"{table}.parquet")
    return result
