#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST_JSON = ROOT / "data" / "latest.json"


def fail(message: str) -> None:
    print(f"VALIDATION FAILED: {message}")
    sys.exit(1)


def main() -> None:
    if not LATEST_JSON.exists():
        fail("latest.json does not exist")

    try:
        brief = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Could not read latest.json: {exc}")

    required_top_level = [
        "schema_version",
        "generated_at",
        "cycle_date",
        "top_signals",
        "watch_list",
        "linkedin_angles",
        "items_considered"
    ]

    for field in required_top_level:
        if field not in brief:
            fail(f"brief missing '{field}'")

    if not isinstance(brief["top_signals"], list):
        fail("top_signals must be a list")

    if not isinstance(brief["watch_list"], list):
        fail("watch_list must be a list")

    if not isinstance(brief["linkedin_angles"], list):
        fail("linkedin_angles must be a list")

    for i, item in enumerate(brief["top_signals"], start=1):
        for field in ["id", "headline", "source", "date", "summary", "url", "labels", "score"]:
            if field not in item:
                fail(f"top_signals[{i}] missing '{field}'")

        if "observation" not in item and "why_it_matters" not in item:
            fail(f"top_signals[{i}] missing either 'observation' or 'why_it_matters'")

    print("VALIDATION OK")


if __name__ == "__main__":
    main()
