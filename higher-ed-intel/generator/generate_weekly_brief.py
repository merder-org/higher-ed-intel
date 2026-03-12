#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

import feedparser
from dateutil import tz

ET = tz.gettz("America/New_York")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARCHIVE = DATA / "archive"
CFG_PATH = Path(__file__).resolve().parent / "config.json"


def now_et() -> datetime:
    return datetime.now(tz=ET)


def monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def fingerprint(title: str, url: str) -> str:
    raw = f"{title.lower().strip()}|{url.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def load_config() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def clean_title(t: str) -> str:
    t = html.unescape(t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("\xa0", " ")
    t = normalize(t)
    t = re.sub(r"\s+\(([A-Z]{1,5})\)\s*$", "", t)
    return t


def clamp_summary(s: str, n: int = 420) -> str:
    if not s:
        return ""

    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)

    junk_patterns = [
        r"Content Files.*",
        r"Metadata download.*",
        r"All Content and Metadata.*",
        r"Descriptive Metadata.*",
        r"Preservation Metadata.*",
        r"PDF XML TEXT.*",
    ]
    for pattern in junk_patterns:
        s = re.sub(pattern, "", s, flags=re.IGNORECASE)

    s = s.replace("\xa0", " ")
    s = normalize(s)
    return s[:n]


def parse_dt(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        st = getattr(entry, key, None)
        if st:
            try:
                return datetime(*st[:6], tzinfo=tz.UTC).astimezone(ET)
            except Exception:
                pass
    return None


def relevant_to_higher_ed(text: str) -> bool:
    t = (text or "").lower()
    keywords = [
        "higher education",
        "college",
        "community college",
        "university",
        "student aid",
        "pell",
        "fafsa",
        "academic advising",
        "advisor",
        "workforce training",
        "education department",
        "student success",
        "retention",
        "transfer",
        "ai in education",
        "education technology",
        "edtech",
    ]
    return any(k in t for k in keywords)


def pick_category(text: str, rules: List[dict]) -> Tuple[Optional[str], int]:
    t = (text or "").lower()
    best_cat = None
    best_hits = 0

    for rule in rules:
        hits = sum(1 for kw in rule.get("keywords", []) if kw.lower() in t)
        if hits > best_hits:
            best_hits = hits
            best_cat = rule.get("category")

    return best_cat, best_hits


def score(category: str, hits: int, text: str) -> int:
    s = hits * 2

    if category == "MA Budget / SUCCESS":
        s += 6
    elif category == "Federal Policy":
        s += 5
    elif category == "Academic Advising":
        s += 4
    elif category == "AI in Higher Ed":
        s += 4

    t = (text or "").lower()
    bonus = [
        "community college",
        "massachusetts",
        "pell",
        "workforce pell",
        "fafsa",
        "rulemaking",
        "appropriation",
        "ways and means",
        "student success",
        "transfer",
        "retention",
        "artificial intelligence",
        "chatgpt",
    ]
    for kw in bonus:
        if kw in t:
            s += 1

    return s


def inject_static_items(cfg: dict) -> List[dict]:
    items: List[dict] = []
    for item in cfg.get("static_items", []):
        items.append(
            {
                "id": fingerprint(item["title"], item["url"]),
                "category": item["category"],
                "title": item["title"],
                "url": item["url"],
                "source": item.get("source", "Static"),
                "published": item.get("published", "N/A"),
                "summary": clamp_summary(item.get("summary", "")),
                "why_it_matters": normalize(item.get("why_it_matters", "")),
                "tags": item.get("tags", []),
                "score": int(item.get("score", 10)),
            }
        )
    return items


def make_summary_for_brief(item: dict) -> str:
    summary = normalize(item.get("summary", ""))
    if summary:
        return summary

    why = normalize(item.get("why_it_matters", ""))
    if why:
        return why

    return f"{item.get('title', 'This item')} surfaced in the latest run as relevant to community colleges."


def make_why_it_matters(item: dict) -> str:
    why = normalize(item.get("why_it_matters", ""))
    if why:
        return why

    cat = item.get("category", "")
    if cat == "MA Budget / SUCCESS":
        return "Potential implications for Massachusetts funding, wraparound supports, transfer, and student success infrastructure."
    if cat == "Federal Policy":
        return "Could affect aid eligibility, workforce pathways, grants, reporting, or institutional compliance."
    if cat == "Academic Advising":
        return "Relevant to advising practice, student persistence, retention strategy, and transfer support."
    if cat == "AI in Higher Ed":
        return "Relevant to AI governance, staff development, classroom use, or student-support operations."
    return "Potentially relevant to community-college leadership, advising, or policy planning."


def build_top_signals(items: List[dict]) -> List[dict]:
    top = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:6]
    out = []
    for item in top:
        enriched = dict(item)
        enriched["summary_for_brief"] = make_summary_for_brief(item)
        enriched["why_it_matters"] = make_why_it_matters(item)
        out.append(enriched)
    return out


def build_briefing_notes(items: List[dict], categories: List[str]) -> List[dict]:
    notes: List[dict] = []
    for cat in categories:
        cat_items = [x for x in items if x.get("category") == cat]
        cat_items = sorted(cat_items, key=lambda x: x.get("score", 0), reverse=True)[:4]
        for item in cat_items:
            enriched = dict(item)
            enriched["summary_for_brief"] = make_summary_for_brief(item)
            enriched["why_it_matters"] = make_why_it_matters(item)
            notes.append(enriched)
    return notes


def build_linkedin_drafts(items: List[dict]) -> List[dict]:
    ordered = sorted(items, key=lambda x: x.get("score", 0), reverse=True)

    def top(cat: str):
        return next((x for x in ordered if x.get("category") == cat), None)

    if not ordered:
        return [
            {
                "title": "Weekly higher-ed signals",
                "text": (
                    "This week’s higher-ed signals are still taking shape.\n\n"
                    "I’m tracking developments in community college policy, advising, and AI in higher education, and I’ll be watching for the next round of concrete signals that affect student success and institutional planning.\n\n"
                    "#HigherEd #CommunityColleges #StudentSuccess #AcademicAdvising #AIinEducation"
                ),
            }
        ]

    ma = top("MA Budget / SUCCESS") or ordered[0]
    fed = top("Federal Policy") or top("Academic Advising") or ordered[min(1, len(ordered) - 1)]
    ai = top("AI in Higher Ed") or ordered[min(2, len(ordered) - 1)]

    drafts = []

    drafts.append(
        {
            "title": "Massachusetts community college policy watch",
            "text": (
                f"One Massachusetts development worth watching this week is {ma['title']} ({ma['url']}).\n\n"
                f"{make_summary_for_brief(ma)}\n\n"
                "What stands out to me is that community college policy in Massachusetts is increasingly about more than access alone. "
                "The deeper issue is whether institutions have enough advising, transfer, and wraparound-support capacity to convert access into persistence and completion.\n\n"
                f"Why this matters: {make_why_it_matters(ma)}\n\n"
                "For colleges, that is where the real work is.\n\n"
                "#Massachusetts #CommunityColleges #StudentSuccess #AcademicAdvising #HigherEdPolicy"
            ),
        }
    )

    drafts.append(
        {
            "title": "Federal higher-ed policy watch",
            "text": (
                f"A federal higher-ed development on my radar this week is {fed['title']} ({fed['url']}).\n\n"
                f"{make_summary_for_brief(fed)}\n\n"
                "The most important thing about developments like this is not just the policy language itself. "
                "It is the operational effect on colleges: advising conversations, aid guidance, workforce programming, reporting obligations, and institutional planning.\n\n"
                f"Why this matters: {make_why_it_matters(fed)}\n\n"
                "Community colleges are often the institutions that feel these shifts first.\n\n"
                "#HigherEdPolicy #CommunityColleges #FinancialAid #StudentSuccess #AcademicAdvising"
            ),
        }
    )

    drafts.append(
        {
            "title": "AI in higher ed: practical implications",
            "text": (
                f"One AI-related higher-ed signal I’m tracking this week is {ai['title']} ({ai['url']}).\n\n"
                f"{make_summary_for_brief(ai)}\n\n"
                "The real issue for colleges is not whether AI is coming. It is whether institutions can move beyond hype and define useful, governed, student-centered applications. "
                "That is especially important in advising, teaching, and student-support settings.\n\n"
                f"Why this matters: {make_why_it_matters(ai)}\n\n"
                "The colleges that benefit most will likely be the ones that combine experimentation with clear guardrails, staff development, and a strong sense of where human judgment still matters most.\n\n"
                "#AIinEducation #HigherEdLeadership #AcademicAdvising #StudentSuccess #EdTech"
            ),
        }
    )

    return drafts


def write_rss(site_title: str, site_link: str, items: List[dict], out_path: Path, build_dt: datetime) -> None:
    now = build_dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    top = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:25]

    parts = [
        '<?xml version="1.0" encoding="UTF-8" ?>',
        '<rss version="2.0"><channel>',
        f"<title>{escape(site_title)}</title>",
        f"<link>{escape(site_link)}</link>",
        f"<description>{escape('Twice-weekly higher ed briefing.')}</description>",
        f"<lastBuildDate>{escape(now)}</lastBuildDate>",
    ]

    for item in top:
        parts.append("<item>")
        parts.append(f"<title>{escape(item.get('title', ''))}</title>")
        parts.append(f"<link>{escape(item.get('url', ''))}</link>")
        parts.append(f"<guid>{escape(item.get('url', ''))}</guid>")
        parts.append(f"<category>{escape(item.get('category', ''))}</category>")
        desc = item.get("summary_for_brief") or item.get("summary") or item.get("why_it_matters") or ""
        parts.append(f"<description>{escape(desc[:900])}</description>")
        parts.append("</item>")

    parts.append("</channel></rss>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def write_markdown(brief: dict, out_path: Path) -> None:
    lines: List[str] = [
        f"# Higher Ed Intelligence Brief — Week of {brief['week_of']}",
        "",
        f"_Generated: {brief['generated_at']}_",
        "",
        "## LinkedIn-ready drafts",
        "",
    ]

    for draft in brief.get("linkedin_drafts", []):
        lines.extend(
            [
                f"### {draft.get('title', '')}",
                "",
                draft.get("text", "").strip(),
                "",
                "---",
                "",
            ]
        )

    lines.extend(["## Top signals this run", ""])

    for item in brief.get("top_signals", []):
        lines.extend(
            [
                f"### {item.get('title', '')}",
                "",
                f"- Category: {item.get('category', '')}",
                f"- Source: {item.get('source', '')} ({item.get('published', 'N/A')})",
                f"- Link: {item.get('url', '')}",
                f"- Summary: {item.get('summary_for_brief', '')}",
                f"- Why it matters: {item.get('why_it_matters', '')}",
                "",
            ]
        )

    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> None:
    cfg = load_config()
    site = cfg["site"]
    filters = cfg["filters"]

    DATA.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    build_dt = now_et()
    cutoff = build_dt - timedelta(days=int(filters["days_lookback"]))

    items: List[dict] = []
    seen_ids = set()
    feed_errors: List[str] = []

    for item in inject_static_items(cfg):
        if item["id"] not in seen_ids:
            items.append(item)
            seen_ids.add(item["id"])

    for feed in cfg.get("feeds", []):
        try:
            parsed = feedparser.parse(feed["url"])

            if getattr(parsed, "bozo", 0) and getattr(parsed, "bozo_exception", None):
                feed_errors.append(f"{feed.get('name', 'Feed')}: {parsed.bozo_exception}")

            for entry in getattr(parsed, "entries", []):
                title = clean_title(getattr(entry, "title", ""))
                link = normalize(getattr(entry, "link", ""))
                summary = clamp_summary(getattr(entry, "summary", ""))

                combined = f"{title} {summary}"
                if not relevant_to_higher_ed(combined):
                    continue

                dt = parse_dt(entry)
                if dt and dt < cutoff:
                    continue

                category, hits = pick_category(combined, cfg.get("category_rules", []))
                if not category:
                    category = feed.get("default_category", "Academic Advising")

                item = {
                    "id": fingerprint(title, link),
                    "category": category,
                    "title": title,
                    "url": link,
                    "source": feed.get("name", "Feed"),
                    "published": dt.strftime("%Y-%m-%d") if dt else "N/A",
                    "summary": summary,
                    "why_it_matters": "",
                    "tags": [],
                    "score": score(category, hits, combined),
                }

                if item["id"] in seen_ids:
                    continue

                items.append(item)
                seen_ids.add(item["id"])

        except Exception as exc:
            feed_errors.append(f"{feed.get('name', 'Feed')}: {exc}")

    max_total = int(filters["max_items_total"])
    max_per_cat = int(filters["max_items_per_category"])
    categories = [r["category"] for r in cfg.get("category_rules", [])]

    kept: List[dict] = []
    for cat in categories:
        cat_items = [x for x in items if x.get("category") == cat]
        cat_items = sorted(cat_items, key=lambda x: x.get("score", 0), reverse=True)[:max_per_cat]
        kept.extend(cat_items)

    kept = sorted(kept, key=lambda x: x.get("score", 0), reverse=True)[:max_total]

    week = monday_of_week(build_dt.date()).isoformat()

    existing = sorted(ARCHIVE.glob("*.json"), reverse=True)[:16]
    archive_list = [{"label": f"Week of {p.stem}", "url": f"data/archive/{p.name}"} for p in existing]
    archive_list.insert(0, {"label": f"Week of {week}", "url": f"data/archive/{week}.json"})

    top_signals = build_top_signals(kept)
    briefing_notes = build_briefing_notes(kept, categories)
    linkedin_drafts = build_linkedin_drafts(top_signals if top_signals else kept)

    brief = {
        "schema_version": "2.1",
        "week_of": week,
        "generated_at": build_dt.strftime("%Y-%m-%d %H:%M ET"),
        "rss_url": "data/rss.xml",
        "categories": categories,
        "items": kept,
        "top_signals": top_signals,
        "briefing_notes": briefing_notes,
        "linkedin_drafts": linkedin_drafts,
        "archive": archive_list,
        "feed_errors": feed_errors,
    }

    (DATA / "latest.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    (ARCHIVE / f"{week}.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")

    write_markdown(brief, DATA / "latest.md")
    write_markdown(brief, ARCHIVE / f"{week}.md")

    write_rss(site["title"], site["public_base_url"].rstrip("/") + "/", top_signals if top_signals else kept, DATA / "rss.xml", build_dt)

    print(f"OK: wrote latest.json + latest.md + archive/{week}.json + archive/{week}.md ({len(kept)} items).")
    if feed_errors:
        print("Feed warnings:")
        for err in feed_errors:
            print(f" - {err}")


if __name__ == "__main__":
    main()
