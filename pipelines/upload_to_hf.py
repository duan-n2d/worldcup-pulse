from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from common import DATA_DIR, LOGS_DIR, STATE_DIR, read_json, write_json


def download_state_from_hf(repo_id: str, token: str | None) -> None:
    # Skip remote state lookup for local demos before the real Dataset repo is configured.
    if not repo_id or repo_id.startswith("your-username/"):
        write_json(STATE_DIR / "last_run.json", read_json(STATE_DIR / "last_run.json", {"last_successful_run_id": None, "last_successful_at": None}))
        return
    try:
        path = hf_hub_download(repo_id=repo_id, repo_type="dataset", filename="state/last_run.json", token=token)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_DIR.joinpath("last_run.json").write_text(Path(path).read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        write_json(STATE_DIR / "last_run.json", read_json(STATE_DIR / "last_run.json", {"last_successful_run_id": None, "last_successful_at": None}))


def upload_data_to_hf(repo_id: str | None = None, token: str | None = None) -> str:
    repo_id = repo_id or os.environ.get("HF_DATASET_REPO", "your-username/worldcup-pulse-data")
    token = token or os.environ.get("HF_TOKEN")
    if not token or repo_id.startswith("your-username/"):
        return "SKIPPED_NO_HF_TOKEN_OR_REPO"
    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, private=False)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=str(DATA_DIR),
        path_in_repo=".",
        ignore_patterns=["raw/**"],
        commit_message="refresh worldcup pulse lakehouse data",
    )
    return "UPLOADED"
