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

NOISE_TITLES = (
    "headlines",
    "newsmakers",
    "week in review",
    "this week's poll",
    "this week’s poll",
)

CLUSTER_STOPWORDS = {
    "about", "after", "again", "against", "college", "colleges", "community",
    "education", "from", "higher", "into", "more", "new", "news", "plans",
    "status", "that", "their", "this", "with", "week", "what", "when", "where",
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


def clean_title(text: str) -> str:
    text = clean_html(text)
    text = re.sub(r"\s+\(([A-Z]{1,6})\)\s*$", "", text)
    return text


def clamp(text: str, limit: int = 420) -> str:
    text = clean_html(text)

    junk_patterns = [
        r"Content Files.*",
        r"Metadata download.*",
        r"All Content and Metadata.*",
        r"Descriptive Metadata.*",
        r"Preservation Metadata.*",
        r"PDF XML TEXT.*",
        r"The post .*? first appeared on .*?[.]?$",
    ]

    for pattern in junk_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    text = normalize(text)

    if len(text) <= limit:
        return text

    shortened = text[:limit].rsplit(" ", 1)[0]
    return shortened.strip() + "..."


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
        "community colleges",
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

    normalized_title = normalize(title).lower().strip(" .:-")
    if any(
        normalized_title == noise or normalized_title.startswith(f"{noise}:")
        for noise in NOISE_TITLES
    ):
        return False

    if len(normalize(item.get("summary", ""))) < 40:
        return False

    return True


def cluster_tokens(item: dict) -> set[str]:
    text = f"{item.get('headline', '')} {item.get('summary', '')}".lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    return {token for token in tokens if len(token) > 3 and token not in CLUSTER_STOPWORDS}


def same_story_cluster(left: dict, right: dict) -> bool:
    left_text = f"{left.get('headline', '')} {left.get('summary', '')}".lower()
    right_text = f"{right.get('headline', '')} {right.get('summary', '')}".lower()

    anchor_phrases = (
        "workforce pell",
        "free community college",
        "student loan forgiveness",
        "fafsa rollout",
        "college closure",
    )
    if any(anchor in left_text and anchor in right_text for anchor in anchor_phrases):
        return True

    left_tokens = cluster_tokens(left)
    right_tokens = cluster_tokens(right)
    if not left_tokens or not right_tokens:
        return False

    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return overlap >= 4 and overlap / union >= 0.24


def select_top_items(ranked: List[dict], limit: int, per_source: int = 2) -> List[dict]:
    selected: List[dict] = []
    source_counts: Counter = Counter()

    for item in ranked:
        if source_counts[item["source"]] >= per_source:
            continue
        if any(same_story_cluster(item, prior) for prior in selected):
            continue

        selected.append(item)
        source_counts[item["source"]] += 1
        if len(selected) >= limit:
            break

    return selected


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
    text = f"{item.get('headline', '')} {item.get('summary', '')}".lower()

    if "workforce pell" in text:
        return (
            "This is now an implementation story rather than a policy announcement. The useful questions are which programs qualify, "
            "how quickly colleges can build compliant offerings, and whether students receive enough guidance to judge short-term credentials well."
        )

    if "AI" in labels and "WORKFORCE" in labels:
        return (
            "The strategic issue is not simply whether colleges can react faster to AI. It is whether they can distinguish durable capabilities "
            "from short-lived employer demand while giving students guidance that remains useful after the current tool cycle."
        )

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


def build_story_context(item: dict) -> str:
    labels = set(item.get("labels", []))
    headline = item.get("headline", "")
    source = item.get("source", "")
    date = item.get("date", "")
    summary = normalize(item.get("summary", ""))

    opening = f"A recent item from {source}, dated {date}, caught my attention: {headline}."

    if summary:
        development = (
            f"The basic development is this: {summary} "
            "I would want to check the original source before posting any exact figures or institutional claims, "
            "but the direction of the story is clear enough to make it worth thinking about."
        )
    else:
        development = (
            "The source summary is thin, so I would treat this as a prompt for further checking rather than a finished account."
        )

    if "GOVERNANCE" in labels or "LEADERSHIP" in labels:
        pattern = (
            "The broader pattern is the growing pressure on higher education leadership. Presidents and senior leaders are not simply managing campuses; "
            "they are navigating boards, political actors, donors, faculty, students, public narratives, and financial constraints. "
            "That makes leadership in higher education feel less like ordinary administration and more like a contested exercise of institutional power."
        )
    elif "TRANSFER" in labels:
        pattern = (
            "The broader pattern is that transfer is becoming central rather than peripheral. But transfer only works when the infrastructure is boringly reliable: "
            "clear pathways, clean credit movement, current advising information, and enough staff capacity to help students make sense of their options."
        )
    elif "AI" in labels:
        pattern = (
            "The broader pattern is that AI in higher education is moving beyond novelty. The question is shifting from whether colleges should experiment with AI "
            "to whether they can govern it, train people to use it well, and avoid using it as a substitute for the human judgment students still need."
        )
    elif "WORKFORCE" in labels:
        pattern = (
            "The broader pattern is that community colleges are being asked to serve as workforce infrastructure. That role is important, but it also creates pressure: "
            "programs have to move quickly, students need good guidance, and colleges need enough capacity to keep up with labor-market expectations."
        )
    elif "MASSACHUSETTS" in labels:
        pattern = (
            "The Massachusetts angle is that access policy, affordability policy, advising, transfer, and student-success work are all starting to converge. "
            "Opening the door matters, but the real institutional challenge is helping students persist, choose well, and complete."
        )
    else:
        pattern = (
            "The broader pattern is the increasing complexity of higher education. Colleges are being asked to be more responsive, more accountable, more technologically fluent, "
            "and more student-centered, often without a matching increase in operational capacity."
        )

    return "\n\n".join([opening, development, pattern])


def build_editable_linkedin_draft(item: dict) -> str:
    labels = set(item.get("labels", []))
    headline = item.get("headline", "")
    url = item.get("url", "")
    observation = item.get("observation") or build_observation(item)

    summary = normalize(item.get("summary", ""))
    if len(summary) > 260:
        summary = summary[:260].rsplit(" ", 1)[0] + "..."

    paragraphs: List[str] = [headline, summary, observation]

    if "ADVISING" in labels or "TRANSFER" in labels or "STUDENT SUCCESS" in labels:
        question = "The practical test is whether students experience a clearer path and timely human help—not merely another initiative or platform."
    elif "MASSACHUSETTS" in labels:
        question = "For Massachusetts colleges, the question is whether access policy is being matched by advising, transfer, and student-support capacity."
    elif "COMMUNITY COLLEGE" in labels:
        question = "For community colleges, the question is whether the implementation capacity matches the ambition."
    else:
        question = "The part worth watching is what changes operationally for students and the people who support them."

    paragraphs.extend([question, f"Source: {url}"])

    return "\n\n".join(paragraphs)


def build_linkedin_angles(top_signals: List[dict], max_drafts: int = 1) -> List[dict]:
    if not top_signals:
        return [
            {
                "hook": "No strong post this cycle",
                "angle": "Signal quality check",
                "draft": (
                    "I did not see enough fresh, high-signal material this cycle to justify forcing a LinkedIn post.\n\n"
                    "That is preferable to recycling old stories or pretending routine updates are more significant than they are.\n\n"
                    "For now, I would treat this as a cycle for watching rather than posting."
                ),
            }
        ]

    ranked = sorted(top_signals, key=lambda x: x["score"], reverse=True)
    angles: List[dict] = []

    for item in ranked:
        if item["score"] < 18:
            continue

        angles.append(
            {
                "hook": item["headline"],
                "angle": "Best post opportunity this cycle",
                "draft": build_editable_linkedin_draft(item),
            }
        )
        if len(angles) >= max_drafts:
            break

    if not angles:
        angles.append(
            {
                "hook": "Not post-worthy this cycle",
                "angle": "Signal quality check",
                "draft": (
                    "This cycle had some movement, but not enough fresh high-signal change to justify a public post.\n\n"
                    "I would rather wait for a clearer policy, governance, funding, or student-success development than force a post from thin material."
                ),
            }
        )

    return angles[:max_drafts]


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
    lines.extend(["## Draft LinkedIn Briefs for Editing", ""])

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
                title = clean_title(getattr(entry, "title", ""))
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

    selected_raw = select_top_items(
        ranked,
        limit=top_max,
        per_source=int(cfg["filters"].get("max_top_signals_per_source", 2)),
    )

    for raw in selected_raw:
        novelty = novelty_label(raw, recent_index)
        labels = [novelty, *raw["labels"]]
        labels = [label for label in labels if label in ALLOWED_LABELS]

        if len(labels) == 1 and labels[0] in {"NEW", "UPDATED"}:
            continue

        observation = build_observation({**raw, "labels": labels})

        enriched = {
            "id": raw["id"],
            "headline": raw["headline"],
            "source": raw["source"],
            "date": raw["date"],
            "summary": raw["summary"],
            "observation": observation,
            "why_it_matters": observation,  # compatibility with older validator/front end
            "url": raw["url"],
            "labels": labels,
            "score": raw["score"],
        }

        top_signals.append(enriched)

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

    linkedin_angles = build_linkedin_angles(
        top_signals,
        max_drafts=int(cfg["filters"].get("linkedin_drafts_max", 1)),
    )
    pattern = build_editorial(top_signals)

    archive_files = sorted(ARCHIVE.glob("*.json"), reverse=True)[:20]
    archive = [{"label": f"Cycle {p.stem}", "url": f"data/archive/{p.name}"} for p in archive_files]

    current_entry = {"label": f"Cycle {cycle_date}", "url": f"data/archive/{cycle_date}.json"}
    if not any(x["url"] == current_entry["url"] for x in archive):
        archive.insert(0, current_entry)

    brief = {
        "schema_version": "6.2",
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
        "cadence": "Monday / Thursday",
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
            "draft_linkedin_briefs_for_editing",
            "watch_list",
            "archive",
        ],
        "top_signals": top_signals,
        "pattern_this_cycle": pattern,
        "why_this_matters_now": pattern,  # compatibility with older validator/front end
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
