from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
RAW_DIR = DATA_DIR / "raw"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
STATE_DIR = DATA_DIR / "state"
LOGS_DIR = DATA_DIR / "logs"

for directory in [RAW_DIR, BRONZE_DIR, SILVER_DIR, GOLD_DIR, STATE_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def compact_ts() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def append_csv(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if path.exists():
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def canonical_id(value: Any) -> str:
    text = clean_text(value).upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    return text or "UNKNOWN"


def is_placeholder_team(value: Any) -> bool:
    text = clean_text(value).upper().replace("-", "_").replace(" ", "_")
    return bool(
        re.match(r"^(WINNER|LOSER)_MATCH_\d+$", text)
        or re.match(r"^(WINNER|RUNNER_UP)_GROUP_[A-L]$", text)
        or re.match(r"^3RD_GROUP_[A-L_]+$", text)
    )


def first_present(obj: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in obj and obj[key] not in [None, ""]:
            return obj[key]
    return default
