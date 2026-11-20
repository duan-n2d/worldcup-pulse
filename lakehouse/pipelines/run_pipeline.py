from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone

from bronze import build_bronze
from common import LOGS_DIR, STATE_DIR, append_csv, compact_ts, iso_now, write_json
from gold import build_gold
from ingest import ingest_worldcup26
from quality_checks import run_quality_checks
from silver import build_silver
from upload_to_hf import download_state_from_hf, upload_data_to_hf


def run(source: str, mode: str, use_mock: bool = False) -> dict:
    if source != "worldcup26":
        raise ValueError("Only --source worldcup26 is supported")
    run_id = f"{compact_ts()}_{uuid.uuid4().hex[:8]}"
    started = datetime.now(timezone.utc)
    row = {"run_id": run_id, "started_at": started.isoformat(), "finished_at": "", "status": "Running", "rows_bronze": 0, "rows_silver": 0, "rows_gold": 0, "error_message": ""}
    try:
        # Best effort: local pipeline should still work without HF secrets.
        repo = os.environ.get("HF_DATASET_REPO", "your-username/worldcup-pulse-data")
        token = os.environ.get("HF_TOKEN")
        download_state_from_hf(repo, token)

        raw_paths = ingest_worldcup26(mode=mode, use_mock=use_mock)
        bronze = build_bronze(raw_paths)
        silver = build_silver()
        gold = build_gold()
        quality_report, quality_passed = run_quality_checks()
        if not quality_passed:
            failed = quality_report[quality_report["status"].eq("Fail")]
            raise RuntimeError("Data quality failed: " + "; ".join(failed["table"].astype(str) + "." + failed["check_name"].astype(str) + "=" + failed["message"].astype(str)))
        upload_status = upload_data_to_hf(repo, token, used_mock=use_mock)
        row.update({
            "status": "Success" if upload_status == "UPLOADED" else "SuccessLocalNoUpload",
            "rows_bronze": sum(len(x) for x in bronze.values()),
            "rows_silver": sum(len(x) for x in silver.values()),
            "rows_gold": sum(len(x) for x in gold.values()),
            "error_message": "" if upload_status == "UPLOADED" else upload_status,
        })
        write_json(STATE_DIR / "last_run.json", {"last_successful_run_id": run_id, "last_successful_at": iso_now(), "source": source, "mode": mode, "used_mock": use_mock})
        return row
    except Exception as exc:
        row.update({"status": "Fail", "error_message": str(exc)})
        raise
    finally:
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        append_csv(LOGS_DIR / "pipeline_runs.csv", row)
        print(row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="worldcup26")
    # Every run pulls each endpoint in full; --mode is only recorded in the manifest and run log.
    parser.add_argument("--mode", choices=["incremental", "full"], default="full")
    parser.add_argument(
        "--use-mock",
        action="store_true",
        default=os.environ.get("WORLDCUP_USE_MOCK", "").strip().lower() in {"1", "true", "yes"},
        help="Use the bundled mock payload instead of the API (offline demo only; never uploaded). Also WORLDCUP_USE_MOCK=1.",
    )
    args = parser.parse_args()
    run(args.source, args.mode, use_mock=args.use_mock)
