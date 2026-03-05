#!/usr/bin/env python3
"""
Higher Ed Intelligence Agent - weekly generator

- Pulls RSS feeds
- Categorizes via keyword rules
- Scores + de-dupes
- Writes latest.json + archive + rss.xml

Design goals:
- Works with free/public RSS sources
- No paywall scraping
- Safe to run in GitHub Actions, cron, NAS scheduler, etc.
"""

from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import feedparser
from dateutil import tz
from xml.sax.saxutils import escape

ET = tz.gettz("America/New_York")

ROOT = Path(__file__).resolve().parents[1]          # .../higher-ed-intel
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
    h = hashlib.sha256((title.lower().strip() + "|" + url.strip()).encode("utf-8")).hexdigest()
    return h[:16]

def load_config() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))

def pick_category(text: str, rules: List[dict]) -> Tuple[Optional[str], int]:
    t = text.lower()
    best_cat = None
    best_hits = 0
    for r in rules:
        hits = sum(1 for kw in r["keywords"] if kw.lower() in t)
        if hits > best_hits:
            best_hits = hits
            best_cat = r["category"]
    return best_cat, best_hits

def score(category: str, hits: int, text: str) -> int:
    s = hits * 2
    # category priors
    if category == "MA Budget / SUCCESS": s += 6
    if category == "Federal Policy": s += 5
    if category == "Academic Advising": s += 4
    if category == "AI in Higher Ed": s += 4

    tl = text.lower()
    for bonus_kw in ["community college", "massachusetts", "pell", "workforce pell", "fa fsa", "rulemaking", "appropriation", "ways and means", "student success"]:
        if bonus_kw in tl:
            s += 1
    return s

def parse_dt(entry) -> Optional[datetime]:
    # feedparser provides *_parsed in struct_time (UTC-ish); convert best-effort
    for key in ("published_parsed", "updated_parsed"):
        st = getattr(entry, key, None)
        if st:
            try:
                return datetime(*st[:6], tzinfo=tz.UTC).astimezone(ET)
            except Exception:
                pass
    return None

def clamp_summary(s: str, n: int = 420) -> str:
    s = normalize(re.sub(r"<[^>]+>", " ", s))  # strip crude HTML tags
    return s[:n]

def inject_static_items(cfg: dict) -> List[dict]:
    # Always include these anchor links, so MA SUCCESS tracking is never “quiet”.
    anchors = cfg.get("static_items", [])
    out = []
    for a in anchors:
        out.append({
            "id": fingerprint(a["title"], a["url"]),
            "category": a["category"],
            "title": a["title"],
            "url": a["url"],
            "source": a.get("source", "Static"),
            "published": a.get("published", "N/A"),
            "summary": a.get("summary", ""),
            "why_it_matters": a.get("why_it_matters", ""),
            "tags": a.get("tags", []),
            "score": int(a.get("score", 10)),
        })
    return out

def build_linkedin_drafts(brief: dict) -> List[dict]:
    # v1: template-based drafts. Later you can swap in an LLM step.
    items = sorted(brief["items"], key=lambda x: x.get("score", 0), reverse=True)

    def top(cat: str):
        return next((x for x in items if x["category"] == cat), None)

    ma = top("MA Budget / SUCCESS")
    fed = top("Federal Policy")
    ai = top("AI in Higher Ed")

    drafts = []

    if ma:
        drafts.append({
            "title": "MA budget watch: SUCCESS Fund signals",
            "text": (
                "Massachusetts’ Community College SUCCESS Fund (7100-4002) is one of the most concrete examples of policy translating into student-support capacity—"
                "peer mentors, skills workshops, transfer-related activities, and targeted advising.\n\n"
                f"Anchor link I check during budget season: {ma['title']} ({ma['url']})\n\n"
                "Question for colleagues: which SUCCESS-funded intervention has produced the clearest retention/completion gains on your campus?\n\n"
                "#CommunityColleges #StudentSuccess #AcademicAdvising #HigherEdPolicy #Massachusetts"
            )
        })

    if fed:
        drafts.append({
            "title": "Federal policy watch: what community colleges can act on",
            "text": (
                "Federal policy and funding signals matter most when they change what colleges can *do* this semester: aid eligibility, workforce grants, reporting requirements, or program approval.\n\n"
                f"One item on my radar: {fed['title']} ({fed['url']})\n\n"
                "If you’re in advising or student success, what’s the most helpful way you’ve communicated major policy shifts to students—FAQs, short videos, office hours, or targeted messaging?\n\n"
                "#HigherEdPolicy #CommunityColleges #FinancialAid #StudentSuccess #AcademicAdvising"
            )
        })

    if ai:
        drafts.append({
            "title": "AI in higher ed: governance beats hype",
            "text": (
                "AI adoption in higher education is increasingly a governance challenge: approved use cases, human oversight, privacy/procurement, and how we measure impact.\n\n"
                f"One item I’m tracking: {ai['title']} ({ai['url']})\n\n"
                "For student support/advising: what guardrails have worked well at your institution?\n\n"
                "#AIinEducation #HigherEdLeadership #AcademicAdvising #StudentSuccess #EdTech"
            )
        })

    if not drafts:
        drafts.append({
            "title": "Weekly higher-ed signals",
            "text": (
                "This week’s higher-ed signals: policy, student success, and AI.\n\n"
                "I’m building a weekly digest focused on what community colleges can act on—changes that affect advising capacity, funding, and implementation realities.\n\n"
                "#HigherEd #CommunityColleges #StudentSuccess #AcademicAdvising #AIinEducation"
            )
        })

    return drafts[:3]

def write_rss(site_title: str, site_link: str, items: List[dict], out_path: Path, build_dt: datetime):
    now = build_dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    top = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:25]

    parts = [
        '<?xml version="1.0" encoding="UTF-8" ?>',
        '<rss version="2.0"><channel>',
        f"<title>{escape(site_title)}</title>",
        f"<link>{escape(site_link)}</link>",
        f"<description>{escape('Weekly briefing with links and LinkedIn-ready drafts.')}</description>",
        f"<lastBuildDate>{escape(now)}</lastBuildDate>",
    ]
    for it in top:
        parts.append("<item>")
        parts.append(f"<title>{escape(it['title'])}</title>")
        parts.append(f"<link>{escape(it['url'])}</link>")
        parts.append(f"<guid>{escape(it['url'])}</guid>")
        parts.append(f"<category>{escape(it['category'])}</category>")
        desc = it.get("summary") or it.get("why_it_matters") or ""
        parts.append(f"<description>{escape(desc[:900])}</description>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    out_path.write_text("\n".join(parts), encoding="utf-8")

def write_markdown(brief: dict, out_path: Path):
    lines = []
    lines.append(f"# Higher Ed Intelligence Brief — Week of {brief['week_of']}")
    lines.append("")
    lines.append(f"_Generated: {brief['generated_at']}_")
    lines.append("")
    lines.append("## Highlights (LinkedIn-ready drafts)")
    lines.append("")

    for d in brief.get("linkedin_drafts", []):
        lines.append(f"### {d['title']}")
        lines.append("")
        lines.append(d["text"].strip())
        lines.append("")
        lines.append("---")
        lines.append("")

    items = brief.get("items", [])
    by_cat = {c: [] for c in brief.get("categories", [])}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)

    lines.append("## This week’s items")
    lines.append("")

    for cat in brief.get("categories", []):
        cat_items = sorted(by_cat.get(cat, []), key=lambda x: x.get("score", 0), reverse=True)
        if not cat_items:
            continue

        lines.append(f"### {cat}")
        lines.append("")
        for it in cat_items:
            pub = it.get("published", "N/A")
            src = it.get("source", "")
            url = it.get("url", "")
            title = it.get("title", "").strip()

            lines.append(f"- **{title}** ({src}, {pub})")
            lines.append(f"  - Link: {url}")

            summary = (it.get("summary") or "").strip()
            if summary:
                lines.append(f"  - Summary: {summary}")

            why = (it.get("why_it_matters") or "").strip()
            if why:
                lines.append(f"  - Why it matters: {why}")

        lines.append("")

    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    
def main():
    cfg = load_config()
    DATA.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    build_dt = now_et()
    cutoff = build_dt - timedelta(days=int(cfg["filters"]["days_lookback"]))

    items: List[dict] = []
    seen_ids = set()

    # Static anchors
    for a in inject_static_items(cfg):
        if a["id"] not in seen_ids:
            items.append(a)
            seen_ids.add(a["id"])

    # RSS feeds
    for feed in cfg["feeds"]:
        parsed = feedparser.parse(feed["url"])
        for e in parsed.entries:
            title = normalize(getattr(e, "title", ""))
            link = normalize(getattr(e, "link", ""))
            summary = clamp_summary(getattr(e, "summary", ""))

            dt = parse_dt(e)
            if dt and dt < cutoff:
                continue

            text = f"{title} {summary}"
            cat, hits = pick_category(text, cfg["category_rules"])
            if not cat:
                cat = feed.get("default_category", "Academic Advising")

            it = {
                "id": fingerprint(title, link),
                "category": cat,
                "title": title,
                "url": link,
                "source": feed["name"],
                "published": dt.strftime("%Y-%m-%d") if dt else "N/A",
                "summary": summary,
                "why_it_matters": "",   # optional: fill later with your own commentary
                "tags": [],
                "score": score(cat, hits, text),
            }
            if it["id"] in seen_ids:
                continue
            items.append(it)
            seen_ids.add(it["id"])

    # Limit per category / total
    max_total = int(cfg["filters"]["max_items_total"])
    max_per_cat = int(cfg["filters"]["max_items_per_category"])

    cats = [r["category"] for r in cfg["category_rules"]]
    kept: List[dict] = []
    for c in cats:
        c_items = [x for x in items if x["category"] == c]
        c_items = sorted(c_items, key=lambda x: x.get("score", 0), reverse=True)[:max_per_cat]
        kept.extend(c_items)

    kept = sorted(kept, key=lambda x: x.get("score", 0), reverse=True)[:max_total]

    week = monday_of_week(build_dt.date()).isoformat()

    # Archive pointer list (last 16 weeks)
    existing = sorted(ARCHIVE.glob("*.json"), reverse=True)[:16]
    archive_list = [{"label": f"Week of {p.stem}", "url": f"data/archive/{p.name}"} for p in existing]
    # Ensure current week appears at top
    archive_list.insert(0, {"label": f"Week of {week}", "url": f"data/archive/{week}.json"})

    brief = {
        "schema_version": "1.0",
        "week_of": week,
        "generated_at": build_dt.strftime("%Y-%m-%d %H:%M ET"),
        "rss_url": "data/rss.xml",
        "categories": cats,
        "items": kept,
        "linkedin_drafts": [],
        "archive": archive_list,
    }

    brief["linkedin_drafts"] = build_linkedin_drafts(brief)

    (DATA / "latest.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    (ARCHIVE / f"{week}.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
write_markdown(brief, DATA / "latest.md")
write_markdown(brief, ARCHIVE / f"{week}.md")
    site = cfg["site"]
    write_rss(site["title"], site["public_base_url"].rstrip("/") + "/", kept, DATA / "rss.xml", build_dt)

    print(f"OK: wrote latest.json + archive/{week}.json ({len(kept)} items).")

if __name__ == "__main__":
    main()
