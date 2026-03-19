#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LATEST_JSON = DATA / "latest.json"


def fail(message: str) -> None:
    print(f"VALIDATION FAILED: {message}")
    sys.exit(1)


def require(obj: dict, field: str, context: str) -> None:
    value = obj.get(field)
    if value is None:
        fail(f"{context} is missing required field '{field}'")
    if isinstance(value, str) and not value.strip():
        fail(f"{context} has empty required field '{field}'")
    if isinstance(value, list) and len(value) == 0:
        fail(f"{context} has empty required list '{field}'")


def main() -> None:
    if not LATEST_JSON.exists():
        fail(f"Missing file: {LATEST_JSON}")

    try:
        brief = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Could not parse latest.json: {exc}")

    require(brief, "schema_version", "brief")
    require(brief, "week_of", "brief")
    require(brief, "generated_at", "brief")
    require(brief, "categories", "brief")
    require(brief, "items", "brief")
    require(brief, "top_signals", "brief")
    require(brief, "linkedin_drafts", "brief")

    top_signals = brief.get("top_signals", [])
    for i, item in enumerate(top_signals, start=1):
        context = f"top_signals[{i}]"
        require(item, "id", context)
        require(item, "title", context)
        require(item, "url", context)
        require(item, "category", context)
        require(item, "summary_for_brief", context)
        require(item, "why_it_matters", context)
        require(item, "core_story", context)
        require(item, "state_relevance", context)
        require(item, "recommended_angle", context)

        story_tags = item.get("story_tags")
        if story_tags is None:
            fail(f"{context} is missing required field 'story_tags'")
        if not isinstance(story_tags, list):
            fail(f"{context} field 'story_tags' must be a list")

        comparison_points = item.get("comparison_points")
        if comparison_points is None:
            fail(f"{context} is missing required field 'comparison_points'")
        if not isinstance(comparison_points, list):
            fail(f"{context} field 'comparison_points' must be a list")

        trigger_tags = {
            "state_budget",
            "credit_for_prior_learning",
            "artificial_intelligence_in_higher_ed",
            "transfer_reform",
            "student_support_infrastructure",
        }

        if any(tag in trigger_tags for tag in story_tags):
            if len(comparison_points) == 0:
                fail(
                    f"{context} has trigger tags {story_tags} but no comparison_points"
                )

    drafts = brief.get("linkedin_drafts", [])
    for i, draft in enumerate(drafts, start=1):
        context = f"linkedin_drafts[{i}]"
        require(draft, "title", context)
        require(draft, "text", context)

    print("VALIDATION OK")


if __name__ == "__main__":
    main()
