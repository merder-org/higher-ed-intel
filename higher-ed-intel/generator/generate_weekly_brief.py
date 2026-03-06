#!/usr/bin/env python3
from __future__ import annotations
import json, re, hashlib
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Optional, Tuple
import feedparser
from dateutil import tz
from xml.sax.saxutils import escape

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
    h = hashlib.sha256((title.lower().strip() + "|" + url.strip()).encode("utf-8")).hexdigest()
    return h[:16]

def load_config() -> dict:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))

def pick_category(text: str, rules: List[dict]) -> Tuple[Optional[str], int]:
    t = (text or "").lower()
    best_cat = None
    best_hits = 0
    for r in rules:
        hits = sum(1 for kw in r.get("keywords", []) if kw.lower() in t)
        if hits > best_hits:
            best_hits = hits
            best_cat = r.get("category")
    return best_cat, best_hits

def score(category: str, hits: int, text: str) -> int:
    s = hits * 2
    if category == "MA Budget / SUCCESS":
        s += 6
    if category == "Federal Policy":
        s += 5
    if category == "Academic Advising":
        s += 4
    if category == "AI in Higher Ed":
        s += 4
    tl = (text or "").lower()
    for kw in ["community college","massachusetts","pell","workforce pell","fafsa","rulemaking","appropriation","ways and means","student success","transfer","ai"]:
        if kw in tl:
            s += 1
    return s

def parse_dt(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        st = getattr(entry, key, None)
        if st:
            try:
                return datetime(*st[:6], tzinfo=tz.UTC).astimezone(ET)
            except Exception:
                pass
    return None

def clamp_summary(s: str, n: int = 420) -> str:
    s = normalize(re.sub(r"<[^>]+>", " ", s or ""))
    return s[:n]

def inject_static_items(cfg: dict) -> List[dict]:
    out = []
    for a in cfg.get("static_items", []):
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
    items = sorted(brief.get("items", []), key=lambda x: x.get("score", 0), reverse=True)
    def top(cat: str):
        return next((x for x in items if x.get("category") == cat), None)
    ma = top("MA Budget / SUCCESS")
    fed = top("Federal Policy")
    ai = top("AI in Higher Ed")
    drafts = []
    if ma:
        drafts.append({"title":"Massachusetts community college policy watch","text":(
            f"One Massachusetts item I’m tracking this week is {ma['title']} ({ma['url']}).\n\n"
            "I’m especially interested in how state funding, transfer policy, and wraparound supports translate into day-to-day student success work on community college campuses.\n\n"
            "What Massachusetts policy development is most likely to affect advising and persistence where you are?\n\n"
            "#Massachusetts #CommunityColleges #StudentSuccess #AcademicAdvising #HigherEdPolicy")})
    if fed:
        drafts.append({"title":"Federal higher-ed policy watch","text":(
            f"A federal item on my radar this week: {fed['title']} ({fed['url']}).\n\n"
            "For community colleges, the most important question is never just what changed in policy language—it’s how quickly the change affects advising, aid eligibility, workforce programs, or student support operations.\n\n"
            "#HigherEdPolicy #CommunityColleges #FinancialAid #StudentSuccess #AcademicAdvising")})
    if ai:
        drafts.append({"title":"AI in higher ed: governance over hype","text":(
            f"One AI-in-higher-ed item I’m tracking this week: {ai['title']} ({ai['url']}).\n\n"
            "The institutions that benefit most from AI will be the ones that define clear use cases, human oversight, and measurable outcomes—especially in teaching, advising, and student support.\n\n"
            "#AIinEducation #HigherEdLeadership #AcademicAdvising #StudentSuccess #EdTech")})
    if not drafts:
        drafts.append({"title":"Weekly higher-ed signals","text":(
            "This week’s higher-ed signals: policy, student success, and AI.\n\n"
            "I’m building a weekly digest focused on what community colleges can act on—changes that affect advising capacity, funding, and implementation realities.\n\n"
            "#HigherEd #CommunityColleges #StudentSuccess #AcademicAdvising #AIinEducation")})
    return drafts[:3]

def write_rss(site_title: str, site_link: str, items: List[dict], out_path: Path, build_dt: datetime) -> None:
    now = build_dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    top = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:25]
    parts = ['<?xml version="1.0" encoding="UTF-8" ?>','<rss version="2.0"><channel>',f"<title>{escape(site_title)}</title>",f"<link>{escape(site_link)}</link>",f"<description>{escape('Weekly briefing with links and LinkedIn-ready drafts.')}</description>",f"<lastBuildDate>{escape(now)}</lastBuildDate>"]
    for it in top:
        parts.append("<item>")
        parts.append(f"<title>{escape(it.get('title', ''))}</title>")
        parts.append(f"<link>{escape(it.get('url', ''))}</link>")
        parts.append(f"<guid>{escape(it.get('url', ''))}</guid>")
        parts.append(f"<category>{escape(it.get('category', ''))}</category>")
        desc = it.get("summary") or it.get("why_it_matters") or ""
        parts.append(f"<description>{escape((desc or '')[:900])}</description>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    out_path.write_text("\n".join(parts), encoding="utf-8")

def write_markdown(brief: dict, out_path: Path) -> None:
    lines = []
    lines.append(f"# Higher Ed Intelligence Brief — Week of {brief['week_of']}")
    lines.append("")
    lines.append(f"_Generated: {brief['generated_at']}_")
    lines.append("")
    lines.append("## LinkedIn-ready drafts")
    lines.append("")
    for d in brief.get("linkedin_drafts", []):
        lines.append(f"### {d.get('title', '')}")
        lines.append("")
        lines.append((d.get("text", "") or "").strip())
        lines.append("")
        lines.append("---")
        lines.append("")
    by_cat = {c: [] for c in brief.get("categories", [])}
    for it in brief.get("items", []):
        by_cat.setdefault(it.get("category", "Other"), []).append(it)
    lines.append("## This week’s items")
    lines.append("")
    for cat in brief.get("categories", []):
        cat_items = sorted(by_cat.get(cat, []), key=lambda x: x.get("score", 0), reverse=True)
        if not cat_items:
            continue
        lines.append(f"### {cat}")
        lines.append("")
        for it in cat_items:
            lines.append(f"- **{(it.get('title', '') or '').strip()}** ({it.get('source','')}, {it.get('published','N/A')})")
            lines.append(f"  - Link: {it.get('url','')}")
            summary = (it.get("summary") or "").strip()
            if summary:
                lines.append(f"  - Summary: {summary}")
            why = (it.get("why_it_matters") or "").strip()
            if why:
                lines.append(f"  - Why it matters: {why}")
        lines.append("")
    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

def main() -> None:
    cfg = load_config()
    site = cfg["site"]
    filters = cfg["filters"]
    DATA.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    build_dt = now_et()
    cutoff = build_dt - timedelta(days=int(filters["days_lookback"]))
    items = []
    seen_ids = set()
    for a in inject_static_items(cfg):
        if a["id"] not in seen_ids:
            items.append(a)
            seen_ids.add(a["id"])
    feed_errors = []
    for feed in cfg.get("feeds", []):
        try:
            parsed = feedparser.parse(feed["url"])
            if getattr(parsed, "bozo", 0):
                exc = getattr(parsed, "bozo_exception", None)
                if exc:
                    feed_errors.append(f"{feed.get('name','Feed')}: {exc}")
            for e in getattr(parsed, "entries", []):
                title = normalize(getattr(e, "title", ""))
                link = normalize(getattr(e, "link", ""))
                summary = clamp_summary(getattr(e, "summary", ""))
                dt = parse_dt(e)
                if dt and dt < cutoff:
                    continue
                text = f"{title} {summary}"
                cat, hits = pick_category(text, cfg.get("category_rules", []))
                if not cat:
                    cat = feed.get("default_category", "Academic Advising")
                it = {
                    "id": fingerprint(title, link),
                    "category": cat,
                    "title": title,
                    "url": link,
                    "source": feed.get("name", "Feed"),
                    "published": dt.strftime("%Y-%m-%d") if dt else "N/A",
                    "summary": summary,
                    "why_it_matters": "",
                    "tags": [],
                    "score": score(cat, hits, text),
                }
                if it["id"] in seen_ids:
                    continue
                items.append(it)
                seen_ids.add(it["id"])
        except Exception as exc:
            feed_errors.append(f"{feed.get('name','Feed')}: {exc}")
    max_total = int(filters["max_items_total"])
    max_per_cat = int(filters["max_items_per_category"])
    cats = [r["category"] for r in cfg.get("category_rules", [])]
    kept = []
    for c in cats:
        c_items = [x for x in items if x.get("category") == c]
        c_items = sorted(c_items, key=lambda x: x.get("score", 0), reverse=True)[:max_per_cat]
        kept.extend(c_items)
    kept = sorted(kept, key=lambda x: x.get("score", 0), reverse=True)[:max_total]
    week = monday_of_week(build_dt.date()).isoformat()
    existing = sorted(ARCHIVE.glob("*.json"), reverse=True)[:16]
    archive_list = [{"label": f"Week of {p.stem}", "url": f"data/archive/{p.name}"} for p in existing]
    archive_list.insert(0, {"label": f"Week of {week}", "url": f"data/archive/{week}.json"})
    brief = {
        "schema_version": "1.1",
        "week_of": week,
        "generated_at": build_dt.strftime("%Y-%m-%d %H:%M ET"),
        "rss_url": "data/rss.xml",
        "categories": cats,
        "items": kept,
        "linkedin_drafts": [],
        "archive": archive_list,
        "feed_errors": feed_errors,
    }
    brief["linkedin_drafts"] = build_linkedin_drafts(brief)
    (DATA / "latest.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    (ARCHIVE / f"{week}.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(brief, DATA / "latest.md")
    write_markdown(brief, ARCHIVE / f"{week}.md")
    write_rss(site["title"], site["public_base_url"].rstrip("/") + "/", kept, DATA / "rss.xml", build_dt)
    print(f"OK: wrote latest.json + latest.md + archive/{week}.json + archive/{week}.md ({len(kept)} items).")
    if feed_errors:
        print("Feed warnings:")
        for err in feed_errors:
            print(f" - {err}")

if __name__ == "__main__":
    main()
