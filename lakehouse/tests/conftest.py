import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

PIPELINES = Path(__file__).resolve().parents[1] / "pipelines"


@pytest.fixture(scope="session")
def mock_run(tmp_path_factory):
    """Run the full pipeline once on the bundled mock payload in an isolated DATA_DIR."""
    data_dir = tmp_path_factory.mktemp("lakehouse")
    env = {**os.environ, "DATA_DIR": str(data_dir)}
    env.pop("HF_TOKEN", None)
    env.pop("HF_DATASET_REPO", None)
    proc = subprocess.run(
        [sys.executable, "run_pipeline.py", "--use-mock"],
        cwd=PIPELINES, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    gold = {p.stem: pd.read_parquet(p) for p in (data_dir / "gold").glob("*.parquet")}
    return {"data_dir": data_dir, "stdout": proc.stdout, "gold": gold}
