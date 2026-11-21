"""Rebuild Silver and Gold from a Bronze snapshot already published to the HF Dataset.

The WorldCup26 API went offline after the tournament, so the source can no longer be
re-pulled. Bronze holds the API payloads as received, so the current Silver/Gold code
can be replayed on it. Usage:

    python replay_from_hf.py --revision <hf-dataset-commit> [--upload]

Without --upload the rebuilt lakehouse stays in DATA_DIR. With --upload it is
published only if every Fail-severity quality check passes.
"""
from __future__ import annotations

import argparse
import os
import shutil
import uuid
from datetime import datetime, timezone

from huggingface_hub import hf_hub_download, snapshot_download

from common import BRONZE_DIR, DATA_DIR, LOGS_DIR, STATE_DIR, append_csv, compact_ts, iso_now, write_json
from gold import build_gold
from quality_checks import run_quality_checks
from silver import build_silver
from upload_to_hf import upload_data_to_hf

EXPECTED_GAMES = 104  # 2026 format: 72 group matches + 32 knockout matches


def replay(repo: str, revision: str, token: str | None, upload: bool) -> dict:
    run_id = f"{compact_ts()}_{uuid.uuid4().hex[:8]}"
    row = {"run_id": run_id, "started_at": iso_now(), "finished_at": "", "status": "Running",
           "rows_bronze": 0, "rows_silver": 0, "rows_gold": 0, "error_message": f"replay of bronze@{revision[:12]}"}
    try:
        snap = snapshot_download(repo, repo_type="dataset", revision=revision, token=token,
                                 allow_patterns=["bronze/*.parquet"], local_dir=DATA_DIR / "_replay_src")
        for f in BRONZE_DIR.glob("*.parquet"):
            f.unlink()
        for name in os.listdir(os.path.join(snap, "bronze")):
            shutil.copy(os.path.join(snap, "bronze", name), BRONZE_DIR / name)
        # Keep the published run history and append this replay to it.
        try:
            log = hf_hub_download(repo, "logs/pipeline_runs.csv", repo_type="dataset", token=token,
                                  local_dir=DATA_DIR / "_replay_src")
            shutil.copy(log, LOGS_DIR / "pipeline_runs.csv")
        except Exception:
            pass

        import pandas as pd
        games = pd.read_parquet(BRONZE_DIR / "games.parquet")
        if len(games) != EXPECTED_GAMES:
            raise RuntimeError(f"bronze@{revision[:12]} has {len(games)} games, expected {EXPECTED_GAMES}; "
                               "refusing to replay a partial or mock snapshot")

        silver = build_silver()
        gold = build_gold()
        report, passed = run_quality_checks()
        if not passed:
            failed = report[report["status"].eq("Fail")]
            raise RuntimeError("Data quality failed: " + "; ".join(failed["table"] + "." + failed["check_name"]))
        status = upload_data_to_hf(repo, token) if upload else "NOT_UPLOADED_DRY_RUN"
        row.update({
            "status": "Success" if status == "UPLOADED" else "SuccessLocalNoUpload",
            "rows_bronze": len(games),
            "rows_silver": sum(len(x) for x in silver.values()),
            "rows_gold": sum(len(x) for x in gold.values()),
            "error_message": row["error_message"] + ("" if status == "UPLOADED" else f"; {status}"),
        })
        write_json(STATE_DIR / "last_run.json", {"last_successful_run_id": run_id, "last_successful_at": iso_now(),
                                                 "source": "worldcup26", "mode": "replay",
                                                 "bronze_revision": revision, "used_mock": False})
        return row
    except Exception as exc:
        row.update({"status": "Fail", "error_message": f"{row['error_message']}: {exc}"})
        raise
    finally:
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_csv(LOGS_DIR / "pipeline_runs.csv", row)
        print(row)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=os.environ.get("HF_DATASET_REPO", "n2d/worldcup-pulse-data"))
    p.add_argument("--revision", required=True, help="HF Dataset commit whose bronze/ holds real API data")
    p.add_argument("--upload", action="store_true")
    a = p.parse_args()
    print(f"DATA_DIR={DATA_DIR}")
    replay(a.repo, a.revision, os.environ.get("HF_TOKEN"), a.upload)
