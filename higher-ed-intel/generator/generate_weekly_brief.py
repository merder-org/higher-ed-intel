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


def clamp(text: str, limit: int = 300) -> str:
    text = clean_html(text)
    return text[:limit]


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
        "MASSACHUSETTS": ["massachusetts", "mass.gov", "mass d", "massdhe", "masseducate", "massreconnect", "masstransfer"],
        "COMMUNITY COLLEGE": ["community college", "two-year", "cc system"],
        "TRANSFER": ["transfer", "articulation", "credit mobility", "mass transfer"],
        "ADVISING": ["advising", "advisor", "coaching", "case management", "guided pathways"],
        "WORKFORCE": ["workforce", "apprenticeship", "employer", "credential", "short-term"],
        "AFFORDABILITY": ["tuition", "free college", "financial aid", "pell", "affordability"],
        "STUDENT SUCCESS": ["retention", "completion", "persistence", "student success", "wraparound"],
        "AI": ["artificial intelligence", "generative ai", "chatgpt", "ai policy", "copilot", "llm"],
    }
    for label, keywords in rules.items():
        if any(keyword in t for keyword in keywords):
            labels.append(label)

    return [x for x in labels if x in ALLOWED_LABELS]


def should_keep_item(item: dict) -> bool:
    title = item.get("title") or item.get("headline") or ""
    text = f"{title} {item.get('summary','')}".lower()

    required_scope = [
        "massachusetts",
        "community college",
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
        "artificial intelligence",
        "generative ai",
    ]
    if not any(token in text for token in required_scope):
        return False

    hard_excludes = [
        "campus life",
        "sports",
        "rankings",
        "opinion:",
        "sponsored",
        "event recap",
        "photo essay",
        "closure risk",
        "college to close",
        "turnaround effort",
        "proxy advisors",
        "investment adviser",
        "fraternity",
        "campus culture",
    ]
    if any(token in text for token in hard_excludes):
        return False

    return True


def quality_score(item: dict) -> int:
    text = f"{item['title']} {item['summary']} {item['source']}".lower()
    score = 0

    high_signal = {
        "massachusetts": 7,
        "community college": 7,
        "budget": 6,
        "appropriation": 6,
        "house ways and means": 6,
        "senate ways and means": 6,
        "report": 4,
        "data": 4,
        "transfer": 5,
        "advising": 5,
        "student success": 5,
        "workforce": 5,
        "pell": 4,
        "implementation": 4,
        "governance": 3,
        "artificial intelligence": 2,
    }
    for token, points in high_signal.items():
        if token in text:
            score += points

    low_signal = {
        "roundup": -5,
        "newsletter": -4,
        "podcast": -4,
        "opinion": -5,
        "webinar": -4,
    }
    for token, points in low_signal.items():
        if token in text:
            score += points

    age_days = (now_et().date() - item["published_dt"].date()).days if item.get("published_dt") else 7
    score += max(0, 8 - age_days)

    labels = set(item.get("labels", []))
    if "MASSACHUSETTS" in labels:
        score += 6
    if "COMMUNITY COLLEGE" in labels:
        score += 4

    return score


def load_recent_cycles(limit: int = 6) -> List[dict]:
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


def novelty_label(item: dict, recent_index: Dict[str, dict]) -> str:
    prior = recent_index.get(item["id"])
    if not prior:
        return "NEW"

    prior_date = prior.get("date") or prior.get("published") or ""
    if prior_date and item.get("date") and item["date"] > prior_date:
        return "UPDATED"

    prior_summary = normalize(prior.get("summary", "")).lower()
    this_summary = normalize(item.get("summary", "")).lower()
    if prior_summary and this_summary and prior_summary != this_summary:
        return "UPDATED"

    return "UPDATED"


def build_why_it_matters(item: dict) -> str:
    labels = set(item.get("labels", []))

    if "MASSACHUSETTS" in labels and "AFFORDABILITY" in labels:
        return "Access policy is moving, but persistence still depends on advising, financial navigation, and day-to-day capacity on campuses."
    if "TRANSFER" in labels:
        return "Transfer policy only helps students when credits move cleanly and advisors have clear, current pathways."
    if "WORKFORCE" in labels:
        return "Workforce language is easy to announce; the hard part is staffing programs and advising students through fast-changing labor demand."
    if "AI" in labels and "ADVISING" in labels:
        return "AI can reduce friction in routine advising work, but only if colleges invest in training, guardrails, and escalation paths for complex cases."
    if "STUDENT SUCCESS" in labels or "ADVISING" in labels:
        return "Support systems do not scale automatically. Colleges need predictable funding and staffing if completion is a real goal."

    return "This is a practical signal about implementation capacity, not just policy language."


def build_editorial(top_signals: List[dict]) -> str:
    if not top_signals:
        return (
            "This cycle was quiet on high-signal developments. That alone is useful: it suggests institutions should stay focused on execution rather than react to noise."
        )

    labels = Counter(label for item in top_signals for label in item.get("labels", []))
    dominant = [label for label, _ in labels.most_common(3)]

    parts: List[str] = []
    if "MASSACHUSETTS" in dominant:
        parts.append(
            "Massachusetts policy activity continues to center on access and affordability, but the pressure is now on implementation. Access opens the door. Support determines whether students can walk through it."
        )

    if "TRANSFER" in dominant or "ADVISING" in dominant:
        parts.append(
            "Across this cycle, transfer and advising keep showing up together. That is the right pairing. Transfer promises fail when advising teams are understaffed or pathway rules stay unclear."
        )

    if "WORKFORCE" in dominant:
        parts.append(
            "Workforce policy is still expanding faster than institutional capacity. Community colleges are often praised publicly and underfunded privately."
        )

    if not parts:
        parts.append(
            "The strongest signal this cycle is less about announcements and more about execution risk: colleges are being asked to do more with limited operational slack."
        )

    return "\n\n".join(parts[:3])


def build_linkedin_angles(top_signals: List[dict]) -> List[dict]:
    if not top_signals:
        return [
            {
                "hook": "Quiet cycle, useful pause",
                "angle": "No strong post this round",
                "draft": "Quiet cycle this week. No single development cleared the quality bar for posting. That is useful in itself: it is a week to focus on implementation work already on campuses.",
            }
        ]

    ranked = sorted(top_signals, key=lambda x: x["score"], reverse=True)
    picks = ranked[:3]
    angles: List[dict] = []
    for item in picks:
        if item["score"] < 18:
            continue
        hook = f"{item['headline']}"
        angle = "Policy promises are easy. Capacity is expensive."
        draft = (
            f"{item['headline']}\n\n"
            f"{item['summary']}\n\n"
            f"Why I am paying attention: {item['why_it_matters']} "
            "Community colleges can absorb policy change only when advising, transfer operations, and student support are funded like core infrastructure."
        )
        angles.append({"hook": hook, "angle": angle, "draft": draft})

    if not angles:
        angles.append(
            {
                "hook": "Not post-worthy this cycle",
                "angle": "Signal quality check",
                "draft": "This cycle had movement, but not enough high-signal change to justify a public post. I would wait for clearer policy or budget action.",
            }
        )

    return angles[:3]


def to_markdown(brief: dict) -> str:
    lines = [
        f"# Higher-Ed Intelligence Brief — {brief['cycle_date']}",
        "",
        f"_Generated: {brief['generated_at']}_",
        "",
        "## Top Signals This Cycle",
        "",
    ]

    for item in brief["top_signals"]:
        labels = ", ".join(item["labels"])
        lines.extend(
            [
                f"### {item['headline']}",
                f"- Source: {item['source']} ({item['date']})",
                f"- Labels: {labels}",
                f"- Summary: {item['summary']}",
                f"- Why it matters: {item['why_it_matters']}",
                f"- Link: {item['url']}",
                "",
            ]
        )

    lines.extend(["## Why This Matters Now", "", brief["why_this_matters_now"], ""])
    lines.extend(["## Possible LinkedIn Post Angles", ""])

    for angle in brief["linkedin_angles"]:
        lines.extend([
            f"### {angle['hook']}",
            f"- Angle: {angle['angle']}",
            "",
            angle["draft"],
            "",
        ])

    lines.extend(["## Watch List", ""])
    for item in brief["watch_list"]:
        lines.append(f"- {item['headline']} ({item['source']}, {item['date']})")

    return "\n".join(lines).strip() + "\n"







def is_reference_page(headline: str, url: str) -> bool:
    text = f"{headline} {url}".lower()
    reference_tokens = [
        "masseducate",
        "massreconnect",
        "masstransfer",
        "success fund",
        "budget.digital.mass.gov",
        "news clips",
        "anchor page",
    ]
    return any(token in text for token in reference_tokens)

def fallback_from_recent_cycles(recent_cycles: List[dict], limit: int = 8) -> List[dict]:
    items: List[dict] = []
    seen = set()

    def pull_candidates(cycle: dict) -> List[dict]:
        candidates = []
        candidates.extend(cycle.get("items", []))
        candidates.extend(cycle.get("top_signals", []))
        return candidates

    for cycle in recent_cycles:
        for it in pull_candidates(cycle):
            headline = it.get("headline") or it.get("title")
            if not headline:
                continue
            url = it.get("url", "")
            if is_reference_page(headline, url) or headline.strip().lower() == "headlines":
                continue

            summary = it.get("summary") or it.get("summary_for_brief") or "Signal carried from recent cycle due to feed access limits."
            labels = it.get("labels") or extract_labels(f"{headline} {summary}")
            labels = [label for label in labels if label in ALLOWED_LABELS and label not in {"NEW", "UPDATED"}]
            if not labels:
                continue

            item_id = it.get("id") or fingerprint(headline, url)
            if item_id in seen:
                continue

            raw = {
                "id": item_id,
                "title": headline,
                "headline": headline,
                "source": it.get("source", "Recent archive"),
                "date": it.get("date") or it.get("published") or cycle.get("cycle_date") or cycle.get("week_of") or "N/A",
                "published_dt": None,
                "summary": summary,
                "url": url,
                "labels": labels,
                "score": int(it.get("score", 16)),
            }
            if not should_keep_item({"title": headline, "summary": summary}):
                continue
            items.append(raw)
            seen.add(item_id)
            if len(items) >= limit:
                return items
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate high-signal Massachusetts higher-ed brief.")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout summary")
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
    cutoff = build_dt - timedelta(days=int(cfg["filters"]["days_lookback"]))

    items: List[dict] = []
    seen = set()
    feed_errors: List[str] = []

    for feed in cfg["feeds"]:
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
                if published_dt and published_dt < cutoff:
                    continue

                item_id = fingerprint(title, url)
                if item_id in seen:
                    continue

                item = {
                    "id": item_id,
                    "headline": title,
                    "source": feed["name"],
                    "date": published_dt.strftime("%Y-%m-%d") if published_dt else "N/A",
                    "published_dt": published_dt,
                    "summary": summary,
                    "url": url,
                }
                item["labels"] = extract_labels(f"{title} {summary} {feed['name']}")
                if not should_keep_item(item):
                    continue

                item["score"] = quality_score(item)
                items.append(item)
                seen.add(item_id)

        except Exception as exc:
            feed_errors.append(f"{feed['name']}: {exc}")

    recent_cycles = load_recent_cycles()
    recent_index = build_recent_index(recent_cycles)

    if not items:
        items = fallback_from_recent_cycles(recent_cycles, limit=10)

    ranked = sorted(items, key=lambda x: x["score"], reverse=True)

    top_signals: List[dict] = []
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
            "why_it_matters": build_why_it_matters({"labels": labels}),
            "url": raw["url"],
            "labels": labels,
            "score": raw["score"],
        }
        top_signals.append(enriched)
        if len(top_signals) >= int(cfg["filters"].get("top_signals_max", 5)):
            break

    top_signals = top_signals[:5]
    if len(top_signals) < 3:
        top_signals = top_signals[:]

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
                "labels": raw["labels"][:3],
            }
        )
        if len(watch_list) == 4:
            break
    watch_list = watch_list[:4]

    linkedin_angles = build_linkedin_angles(top_signals)

    archive_files = sorted(ARCHIVE.glob("*.json"), reverse=True)[:20]
    archive = [{"label": f"Cycle {p.stem}", "url": f"data/archive/{p.name}"} for p in archive_files]
    current_entry = {"label": f"Cycle {cycle_date}", "url": f"data/archive/{cycle_date}.json"}
    if not any(x["url"] == current_entry["url"] for x in archive):
        archive.insert(0, current_entry)

    brief = {
        "schema_version": "5.0",
        "product": "Massachusetts Higher-Ed Intelligence Brief",
        "focus": [
            "Massachusetts higher education",
            "Community colleges",
            "Advising",
            "Transfer",
            "Student success",
            "Affordability",
            "Workforce policy",
            "Practical AI in teaching/advising",
        ],
        "cadence": "Monday / Wednesday / Friday",
        "generated_at": build_dt.strftime("%Y-%m-%d %H:%M ET"),
        "cycle_date": cycle_date,
        "week_of": week,
        "freshness": {
            "cycle_date": cycle_date,
            "new_count": len([x for x in top_signals if "NEW" in x["labels"]]),
            "updated_count": len([x for x in top_signals if "UPDATED" in x["labels"]]),
        },
        "sections": [
            "top_signals_this_cycle",
            "why_this_matters_now",
            "possible_linkedin_post_angles",
            "watch_list",
            "archive",
        ],
        "top_signals": top_signals,
        "why_this_matters_now": build_editorial(top_signals),
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
        print(f"Top signals: {len(top_signals)} | Watch list: {len(watch_list)} | Items considered: {len(items)}")
        if feed_errors:
            print("Feed warnings:")
            for warning in feed_errors:
                print(f" - {warning}")


if __name__ == "__main__":
    main()
