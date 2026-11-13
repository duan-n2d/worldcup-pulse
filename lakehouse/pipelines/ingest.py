from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from common import RAW_DIR, compact_ts, iso_now, write_json

BASE_URL = "https://worldcup26.ir/get"
ENDPOINTS = {
    "teams": "teams",
    "groups": "groups",
    "games": "games",
    "stadiums": "stadiums",
}


def _safe_get(endpoint: str, timeout: int = 20) -> Any:
    url = f"{BASE_URL}/{endpoint}"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _mock_payload() -> dict[str, Any]:
    teams = [
        {"id": 1, "name": "Canada", "country": "Canada", "fifa_code": "CAN", "flag": "🇨🇦", "group": "A", "rank": 31},
        {"id": 2, "name": "Mexico", "country": "Mexico", "fifa_code": "MEX", "flag": "🇲🇽", "group": "A", "rank": 15},
        {"id": 3, "name": "United States", "country": "United States", "fifa_code": "USA", "flag": "🇺🇸", "group": "A", "rank": 11},
        {"id": 4, "name": "Brazil", "country": "Brazil", "fifa_code": "BRA", "flag": "🇧🇷", "group": "B", "rank": 5},
        {"id": 5, "name": "France", "country": "France", "fifa_code": "FRA", "flag": "🇫🇷", "group": "B", "rank": 2},
        {"id": 6, "name": "Argentina", "country": "Argentina", "fifa_code": "ARG", "flag": "🇦🇷", "group": "B", "rank": 1},
    ]
    stadiums = [
        {"id": 1, "name": "MetLife Stadium", "city": "New York/New Jersey", "country": "USA", "lat": 40.8135, "lon": -74.0745},
        {"id": 2, "name": "Estadio Azteca", "city": "Mexico City", "country": "Mexico", "lat": 19.3029, "lon": -99.1505},
        {"id": 3, "name": "BC Place", "city": "Vancouver", "country": "Canada", "lat": 49.2768, "lon": -123.1119},
    ]
    games = []
    for i in range(1, 13):
        home = teams[(i - 1) % len(teams)]
        away = teams[(i + 1) % len(teams)]
        games.append({
            "id": i,
            "match_number": i,
            "stage": "Group",
            "matchday": (i - 1) // 4 + 1,
            "home_team": home["name"],
            "away_team": away["name"],
            "home_score": i % 4,
            "away_score": (i + 1) % 3,
            "status": "finished",
            "stadium": stadiums[i % 3]["name"],
            "city": stadiums[i % 3]["city"],
            "goals": [
                {"minute": 12 + i, "team": home["name"], "player": f"{home['fifa_code']} Forward", "type": "goal"},
                {"minute": 55 + i, "team": away["name"], "player": f"{away['fifa_code']} Midfielder", "type": "goal"},
            ],
        })
    return {"teams": teams, "groups": [], "games": games, "stadiums": stadiums}


def ingest_worldcup26(mode: str = "incremental") -> dict[str, Path]:
    run_ts = compact_ts()
    snapshot_dir = RAW_DIR / f"worldcup26_{run_ts}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"source": "worldcup26", "mode": mode, "ingested_at": iso_now(), "files": {}}
    payloads: dict[str, Any] = {}
    used_mock = False
    for name, endpoint in ENDPOINTS.items():
        try:
            payloads[name] = _safe_get(endpoint)
        except Exception as exc:
            used_mock = True
            payloads = _mock_payload()
            manifest["warning"] = f"API fallback mock used because endpoint {endpoint} failed: {exc}"
            break
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = snapshot_dir / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["files"][name] = str(path)
        paths[name] = path
    manifest["used_mock"] = used_mock
    write_json(snapshot_dir / "manifest.json", manifest)
    return paths
