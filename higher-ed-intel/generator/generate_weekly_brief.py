#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import feedparser
from dateutil import tz

ET = tz.gettz("America/New_York")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARCHIVE = DATA / "archive"
CFG_PATH = Path(__file__).resolve().parent / "config.json"

ALLOWED_LABELS = {
    "NEW",
    "UPDATED",
    "MASSACHUSETTS",
    "COMMUNITY COLLEGE",
    "TRANSFER",
    "ADVISING",
    "WORKFORCE",
    "AFFORDABILITY",
    "STUDENT SUCCESS",
    "AI",
    "GOVERNANCE",
    "LEADERSHIP",
    "POLICY",
}


def now_et() -> datetime:
    return datetime.now(tz=ET)


def monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def clean_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    return normalize(text)


def clamp(text: str, limit: int = 360) -> str:
    text = clean_html(text)

    junk_patterns = [
        r"Content Files.*",
        r"Metadata download.*",
        r"All Content and Metadata.*",
        r"Descriptive Metadata.*",
        r"Preservation Metadata.*",
        r"PDF XML TEXT.*",
    ]

    for pattern in junk_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    return normalize(text)[:limit]


def fingerprint(title: str, url: str) -> str:
    raw = f"{normalize(title).lower()}|{normalize(url)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def parse_entry_dt(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=tz.UTC).astimezone(ET)
            except Exception:
                pass
    return None


def load_config() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def extract_labels(text: str) -> List[str]:
    t = text.lower()
    labels: List[str] = []

    rules = {
        "MASSACHUSETTS": [
            "massachusetts",
            "mass.gov",
            "massdhe",
            "masseducate",
            "massreconnect",
            "masstransfer",
            "success fund",
        ],
        "COMMUNITY COLLEGE": [
            "community college",
            "community colleges",
            "two-year",
            "cc system",
        ],
        "TRANSFER": [
            "transfer",
            "articulation",
            "credit mobility",
            "mass transfer",
            "masstransfer",
            "credit for prior learning",
            "prior learning assessment",
            "cpl",
        ],
        "ADVISING": [
            "advising",
            "advisor",
            "coaching",
            "case management",
            "guided pathways",
        ],
        "WORKFORCE": [
            "workforce",
            "apprenticeship",
            "employer",
            "credential",
            "short-term",
            "career pathways",
        ],
        "AFFORDABILITY": [
            "tuition",
            "free college",
            "financial aid",
            "pell",
            "affordability",
            "fafsa",
        ],
        "STUDENT SUCCESS": [
            "retention",
            "completion",
            "persistence",
            "student success",
            "wraparound",
        ],
        "AI": [
            "artificial intelligence",
            "generative ai",
            "chatgpt",
            "ai policy",
            "copilot",
            "llm",
        ],
        "GOVERNANCE": [
            "governance",
            "board of trustees",
            "trustees",
            "resignation",
            "president",
            "academic freedom",
            "donor",
            "lawsuit",
            "accreditation",
            "censorship",
        ],
        "LEADERSHIP": [
            "president",
            "resignation",
            "chancellor",
            "provost",
            "college leadership",
            "higher ed leadership",
        ],
        "POLICY": [
            "policy",
            "rulemaking",
            "appropriation",
            "budget",
            "legislation",
            "federal",
            "statewide",
        ],
    }

    for label, keywords in rules.items():
        if any(keyword in t for keyword in keywords):
            labels.append(label)

    return [x for x in labels if x in ALLOWED_LABELS]


def should_keep_item(item: dict) -> bool:
    title = item.get("title") or item.get("headline") or ""
    text = f"{title} {item.get('summary', '')} {item.get('source', '')}".lower()

    required_scope = [
        "massachusetts",
        "community college",
        "higher education",
        "college",
        "university",
        "advis",
        "transfer",
        "student success",
        "retention",
        "completion",
        "afford",
        "workforce",
        "pell",
        "credential",
        "tuition",
        "fafsa",
        "artificial intelligence",
        "generative ai",
        "academic freedom",
        "governance",
        "board of trustees",
        "president",
        "resignation",
        "credit for prior learning",
        "prior learning assessment",
    ]

    if not any(token in text for token in required_scope):
        return False

    hard_excludes = [
        "sports",
        "rankings",
        "sponsored",
        "photo essay",
        "proxy advisors",
        "investment adviser",
        "fraternity",
    ]

    if any(token in text for token in hard_excludes):
        return False

    return True


def load_recent_cycles(limit: int = 8) -> List[dict]:
    cycles: List[dict] = []
    for path in sorted(ARCHIVE.glob("*.json"), reverse=True)[:limit]:
        try:
            cycles.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return cycles


def build_recent_index(cycles: List[dict]) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for cycle in cycles:
        for item in cycle.get("top_signals", []):
            idx = item.get("id")
            if idx and idx not in index:
                index[idx] = item
    return index


def recent_seen_ids(cycles: List[dict]) -> set[str]:
    seen: set[str] = set()
    for cycle in cycles:
        for section in ("top_signals", "watch_list"):
            for item in cycle.get(section, []):
                if item.get("id"):
                    seen.add(item["id"])
    return seen


def novelty_label(item: dict, recent_index: Dict[str, dict]) -> str:
    prior = recent_index.get(item["id"])
    if not prior:
        return "NEW"

    prior_summary = normalize(prior.get("summary", "")).lower()
    this_summary = normalize(item.get("summary", "")).lower()

    if prior_summary and this_summary and prior_summary != this_summary:
        return "UPDATED"

    return "UPDATED"


def quality_score(item: dict, build_dt: datetime, recent_ids: set[str]) -> int:
    text = f"{item['headline']} {item['summary']} {item['source']}".lower()
    score = 0

    high_signal = {
        "massachusetts": 9,
        "community college": 8,
        "community colleges": 8,
        "budget": 7,
        "appropriation": 7,
        "house ways and means": 7,
        "senate ways and means": 7,
        "report": 4,
        "data": 4,
        "transfer": 6,
        "credit for prior learning": 7,
        "prior learning assessment": 7,
        "advising": 6,
        "student success": 6,
        "workforce": 6,
        "pell": 5,
        "fafsa": 5,
        "implementation": 4,
        "governance": 7,
        "board of trustees": 7,
        "resignation": 7,
        "president": 5,
        "academic freedom": 7,
        "donor": 5,
        "lawsuit": 5,
        "artificial intelligence": 4,
        "generative ai": 4,
    }

    for token, points in high_signal.items():
        if token in text:
            score += points

    low_signal = {
        "roundup": -6,
        "newsletter": -5,
        "podcast": -5,
        "webinar": -5,
        "newsmakers": -6,
        "event recap": -5,
    }

    for token, points in low_signal.items():
        if token in text:
            score += points

    published_dt = item.get("published_dt")
    if not published_dt:
        return -999

    age_days = max(0, (build_dt.date() - published_dt.date()).days)

    if age_days <= 1:
        score += 14
    elif age_days <= 3:
        score += 10
    elif age_days <= 5:
        score += 5
    elif age_days <= 7:
        score -= 4
    else:
        score -= 12

    labels = set(item.get("labels", []))

    if "MASSACHUSETTS" in labels:
        score += 7
    if "COMMUNITY COLLEGE" in labels:
        score += 5
    if "GOVERNANCE" in labels:
        score += 6
    if "LEADERSHIP" in labels:
        score += 5
    if "POLICY" in labels:
        score += 4

    if item["id"] in recent_ids:
        score -= 18

    return score


def build_observation(item: dict) -> str:
    labels = set(item.get("labels", []))

    if "GOVERNANCE" in labels or "LEADERSHIP" in labels:
        return (
            "The larger issue here is how power is being exercised inside higher education institutions, "
            "especially when boards, presidents, politics, donors, faculty, and public scrutiny collide."
        )

    if "MASSACHUSETTS" in labels and "AFFORDABILITY" in labels:
        return (
            "The interesting question is not only whether access expands, but whether campuses have the advising, "
            "financial navigation, and student-support capacity to make that access meaningful."
        )

    if "TRANSFER" in labels:
        return (
            "This is worth watching because transfer reform only becomes real when credits move cleanly, "
            "requirements are legible, and advisors have pathways they can actually trust."
        )

    if "WORKFORCE" in labels:
        return (
            "This connects to a familiar tension: colleges are being asked to respond quickly to workforce needs, "
            "but the staffing and support infrastructure often lags behind the rhetoric."
        )

    if "AI" in labels and "ADVISING" in labels:
        return (
            "The practical question is whether AI reduces friction for students and staff, or simply adds another layer "
            "of tools that people have to manage."
        )

    if "AI" in labels:
        return (
            "The AI conversation is starting to move from novelty toward implementation: governance, training, workload, "
            "equity, and the points where human judgment still matters."
        )

    if "STUDENT SUCCESS" in labels or "ADVISING" in labels:
        return (
            "The part that caught my attention is the operational burden. Student success work does not scale by aspiration alone."
        )

    return (
        "This seems less like a one-off story than a small sign of the pressure now being placed on colleges to do more, "
        "explain more, and absorb more complexity."
    )


def build_editorial(top_signals: List[dict]) -> str:
    if not top_signals:
        return (
            "I did not find enough fresh, high-signal items in the current feed window. "
            "That is better than recycling old stories and pretending they are new."
        )

    labels = Counter(label for item in top_signals for label in item.get("labels", []))
    dominant = [label for label, _ in labels.most_common(4)]

    parts: List[str] = []

    if "GOVERNANCE" in dominant or "LEADERSHIP" in dominant:
        parts.append(
            "The most interesting thread this cycle is governance: how decisions get made, who gets heard, "
            "and how institutional authority is being tested."
        )

    if "MASSACHUSETTS" in dominant:
        parts.append(
            "The Massachusetts thread remains less about access in the abstract and more about whether colleges have enough capacity "
            "to support students once the door is open."
        )

    if "TRANSFER" in dominant or "ADVISING" in dominant:
        parts.append(
            "Transfer and advising continue to belong in the same conversation. Pathways do not help much unless someone can explain them clearly to students."
        )

    if "WORKFORCE" in dominant:
        parts.append(
            "Workforce alignment keeps showing up as a policy ambition. The harder question is whether colleges are being funded for the complexity of delivering it."
        )

    if "AI" in dominant:
        parts.append(
            "The AI stories worth keeping are not really about tools. They are about institutional judgment, governance, workload, and trust."
        )

    if not parts:
        parts.append(
            "The useful signal this cycle is not a single dramatic announcement, but the accumulation of pressure on colleges to adapt without much spare capacity."
        )

    return "\n\n".join(parts[:3])


def build_linkedin_angles(top_signals: List[dict]) -> List[dict]:
    if not top_signals:
        return [
            {
                "hook": "No strong post this cycle",
                "angle": "Signal quality check",
                "draft": (
                    "I did not see enough fresh, high-signal material this cycle to justify forcing a LinkedIn post. "
                    "That is preferable to recycling old stories or pretending routine updates are more significant than they are."
                ),
            }
        ]

    ranked = sorted(top_signals, key=lambda x: x["score"], reverse=True)
    angles: List[dict] = []

    for item in ranked[:3]:
        if item["score"] < 15:
            continue

        observation = build_observation(item)
        draft = (
            f"{item['headline']}\n\n"
            f"{item['summary']}\n\n"
            f"What caught my attention is this: {observation}\n\n"
            "That seems worth watching."
        )

        if "MASSACHUSETTS" in item.get("labels", []):
            draft += (
                "\n\nFor Massachusetts community colleges, the practical question is whether policy ambition is being matched "
                "by the staffing, advising, and support infrastructure needed to make it real."
            )

        angles.append(
            {
                "hook": item["headline"],
                "angle": "A development worth watching",
                "draft": draft,
            }
        )

    if not angles:
        angles.append(
            {
                "hook": "Not post-worthy this cycle",
                "angle": "Signal quality check",
                "draft": (
                    "This cycle had some movement, but not enough fresh high-signal change to justify a public post. "
                    "I would rather wait for a clearer policy, governance, funding, or student-success development."
                ),
            }
        )

    return angles[:3]


def to_markdown(brief: dict) -> str:
    lines = [
        f"# Higher-Ed Intelligence Brief — {brief['cycle_date']}",
        "",
        f"_Generated: {brief['generated_at']}_",
        "",
        "## Developments Worth Watching",
        "",
    ]

    if not brief["top_signals"]:
        lines.append("_No fresh high-signal items were found in the current feed window._")
        lines.append("")

    for item in brief["top_signals"]:
        labels = ", ".join(item["labels"])
        lines.extend(
            [
                f"### {item['headline']}",
                f"- Source: {item['source']} ({item['date']})",
                f"- Labels: {labels}",
                f"- Summary: {item['summary']}",
                f"- What caught my attention: {item['observation']}",
                f"- Link: {item['url']}",
                "",
            ]
        )

    lines.extend(["## Pattern I’m Seeing", "", brief["pattern_this_cycle"], ""])
    lines.extend(["## Possible LinkedIn Post Angles", ""])

    for angle in brief["linkedin_angles"]:
        lines.extend(
            [
                f"### {angle['hook']}",
                f"- Angle: {angle['angle']}",
                "",
                angle["draft"],
                "",
            ]
        )

    lines.extend(["## Watch List", ""])

    if not brief["watch_list"]:
        lines.append("_No additional fresh watch-list items surfaced._")
    else:
        for item in brief["watch_list"]:
            lines.append(f"- {item['headline']} ({item['source']}, {item['date']})")

    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate high-signal higher-ed brief.")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout summary")

    # Accepted for compatibility with the newer GitHub workflow.
    parser.add_argument("--target-state", default="Massachusetts")
    parser.add_argument("--comparative-mode", default="true")
    parser.add_argument("--force-story-url", default="")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()
    site = cfg["site"]

    DATA.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    build_dt = now_et()
    cycle_date = build_dt.date().isoformat()
    week = monday_of_week(build_dt.date()).isoformat()

    days_lookback = int(cfg["filters"].get("days_lookback", 5))
    cutoff = build_dt - timedelta(days=days_lookback)

    recent_cycles = load_recent_cycles()
    recent_index = build_recent_index(recent_cycles)
    recently_seen = recent_seen_ids(recent_cycles)

    items: List[dict] = []
    seen = set()
    feed_errors: List[str] = []

    for feed in cfg.get("feeds", []):
        try:
            parsed = feedparser.parse(feed["url"])

            if getattr(parsed, "bozo", 0) and getattr(parsed, "bozo_exception", None):
                feed_errors.append(f"{feed['name']}: {parsed.bozo_exception}")

            for entry in getattr(parsed, "entries", []):
                title = clean_html(getattr(entry, "title", ""))
                summary = clamp(getattr(entry, "summary", ""))
                url = normalize(getattr(entry, "link", ""))

                if not title or not url:
                    continue

                published_dt = parse_entry_dt(entry)

                # Strict freshness rule:
                # If the feed does not provide a usable date, do not use the item.
                # If the item is outside the lookback window, do not use it.
                if not published_dt:
                    continue

                if published_dt < cutoff:
                    continue

                item_id = fingerprint(title, url)
                if item_id in seen:
                    continue

                item = {
                    "id": item_id,
                    "headline": title,
                    "source": feed["name"],
                    "date": published_dt.strftime("%Y-%m-%d"),
                    "published_dt": published_dt,
                    "summary": summary,
                    "url": url,
                }

                item["labels"] = extract_labels(f"{title} {summary} {feed['name']}")

                if not should_keep_item(item):
                    continue

                item["score"] = quality_score(item, build_dt, recently_seen)

                # Discard items that are technically relevant but too weak after freshness and repetition penalties.
                if item["score"] < 4:
                    continue

                items.append(item)
                seen.add(item_id)

        except Exception as exc:
            feed_errors.append(f"{feed.get('name', 'Feed')}: {exc}")

    # Optional manual feature URL. It only works if the URL appeared in the feed window.
    force_url = normalize(args.force_story_url)
    if force_url:
        for item in items:
            if normalize(item.get("url", "")) == force_url:
                item["score"] += 25
                break
        else:
            feed_errors.append(
                f"Forced story URL was not found in the current fresh feed window: {force_url}"
            )

    ranked = sorted(items, key=lambda x: x["score"], reverse=True)

    top_signals: List[dict] = []
    top_max = int(cfg["filters"].get("top_signals_max", 5))

    for raw in ranked:
        novelty = novelty_label(raw, recent_index)
        labels = [novelty, *raw["labels"]]
        labels = [label for label in labels if label in ALLOWED_LABELS]

        if len(labels) == 1 and labels[0] in {"NEW", "UPDATED"}:
            continue

        enriched = {
            "id": raw["id"],
            "headline": raw["headline"],
            "source": raw["source"],
            "date": raw["date"],
            "summary": raw["summary"],
            "observation": build_observation({"labels": labels}),
            "url": raw["url"],
            "labels": labels,
            "score": raw["score"],
        }

        top_signals.append(enriched)

        if len(top_signals) >= top_max:
            break

    top_signals = top_signals[:5]

    used_ids = {x["id"] for x in top_signals}
    watch_candidates = [x for x in ranked if x["id"] not in used_ids]

    watch_list = []
    for raw in watch_candidates[:8]:
        watch_list.append(
            {
                "id": raw["id"],
                "headline": raw["headline"],
                "source": raw["source"],
                "date": raw["date"],
                "url": raw["url"],
                "labels": raw["labels"][:4],
                "score": raw["score"],
            }
        )

        if len(watch_list) == 4:
            break

    linkedin_angles = build_linkedin_angles(top_signals)

    archive_files = sorted(ARCHIVE.glob("*.json"), reverse=True)[:20]
    archive = [{"label": f"Cycle {p.stem}", "url": f"data/archive/{p.name}"} for p in archive_files]

    current_entry = {"label": f"Cycle {cycle_date}", "url": f"data/archive/{cycle_date}.json"}
    if not any(x["url"] == current_entry["url"] for x in archive):
        archive.insert(0, current_entry)

    brief = {
        "schema_version": "6.0",
        "product": "Higher-Ed Intelligence Brief",
        "focus": [
            "Massachusetts higher education",
            "Community colleges",
            "Advising",
            "Transfer",
            "Student success",
            "Affordability",
            "Workforce policy",
            "Governance and leadership",
            "Practical AI in teaching/advising",
        ],
        "cadence": "Monday / Wednesday / Friday",
        "generated_at": build_dt.strftime("%Y-%m-%d %H:%M ET"),
        "cycle_date": cycle_date,
        "week_of": week,
        "freshness": {
            "cycle_date": cycle_date,
            "days_lookback": days_lookback,
            "cutoff": cutoff.strftime("%Y-%m-%d %H:%M ET"),
            "new_count": len([x for x in top_signals if "NEW" in x["labels"]]),
            "updated_count": len([x for x in top_signals if "UPDATED" in x["labels"]]),
        },
        "sections": [
            "developments_worth_watching",
            "pattern_im_seeing",
            "possible_linkedin_post_angles",
            "watch_list",
            "archive",
        ],
        "top_signals": top_signals,
        "pattern_this_cycle": build_editorial(top_signals),
        "linkedin_angles": linkedin_angles,
        "watch_list": watch_list,
        "archive": archive,
        "items_considered": len(items),
        "feed_errors": feed_errors,
        "site": site,
    }

    latest_json = DATA / "latest.json"
    cycle_json = ARCHIVE / f"{cycle_date}.json"
    latest_md = DATA / "latest.md"
    cycle_md = ARCHIVE / f"{cycle_date}.md"

    latest_json.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    cycle_json.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")

    md = to_markdown(brief)
    latest_md.write_text(md, encoding="utf-8")
    cycle_md.write_text(md, encoding="utf-8")

    if not args.quiet:
        print(f"OK: wrote {latest_json} and {cycle_json}")
        print(
            f"Fresh window: {days_lookback} days | "
            f"Top signals: {len(top_signals)} | "
            f"Watch list: {len(watch_list)} | "
            f"Items considered: {len(items)}"
        )
        if feed_errors:
            print("Feed warnings:")
            for warning in feed_errors:
                print(f" - {warning}")


if __name__ == "__main__":
    main()
