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


def require(container: dict, key: str, context: str) -> None:
    if key not in container:
        fail(f"{context} missing '{key}'")
    value = container[key]
    if isinstance(value, str) and not value.strip():
        fail(f"{context} has empty '{key}'")


def validate_top_signal(item: dict, idx: int) -> None:
    context = f"top_signals[{idx}]"
    for key in ["id", "headline", "source", "date", "summary", "why_it_matters", "url", "labels", "score"]:
        require(item, key, context)

    if not isinstance(item["labels"], list) or len(item["labels"]) < 2:
        fail(f"{context}.labels must include novelty plus at least one topical label")

    if item["labels"][0] not in {"NEW", "UPDATED"}:
        fail(f"{context}.labels first value must be NEW or UPDATED")


def validate_linkedin_angle(item: dict, idx: int) -> None:
    context = f"linkedin_angles[{idx}]"
    for key in ["hook", "angle", "draft"]:
        require(item, key, context)


def main() -> None:
    if not LATEST_JSON.exists():
        fail(f"Missing {LATEST_JSON}")

    try:
        brief = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Failed to parse latest.json: {exc}")

    for key in [
        "schema_version",
        "product",
        "cadence",
        "generated_at",
        "cycle_date",
        "top_signals",
        "why_this_matters_now",
        "linkedin_angles",
        "watch_list",
        "archive",
        "freshness",
    ]:
        require(brief, key, "brief")

    top_signals = brief["top_signals"]
    if not isinstance(top_signals, list):
        fail("brief.top_signals must be a list")
    if len(top_signals) > 5:
        fail("brief.top_signals must have at most 5 items")

    for i, item in enumerate(top_signals, start=1):
        validate_top_signal(item, i)

    watch_list = brief["watch_list"]
    if not isinstance(watch_list, list):
        fail("brief.watch_list must be a list")
    if len(watch_list) > 4:
        fail("brief.watch_list must have at most 4 items")

    linkedin_angles = brief["linkedin_angles"]
    if not isinstance(linkedin_angles, list):
        fail("brief.linkedin_angles must be a list")
    if len(linkedin_angles) > 3:
        fail("brief.linkedin_angles must have at most 3 items")

    for i, angle in enumerate(linkedin_angles, start=1):
        validate_linkedin_angle(angle, i)

    print("VALIDATION OK")


if __name__ == "__main__":
    main()
