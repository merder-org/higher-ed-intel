#!/usr/bin/env python3
from __future__ import annotations
import json, re, hashlib
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Optional, Tuple
import feedparser
from dateutil import tz
from xml.sax.saxutils import escape
import html

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
    if category == "MA Budget / SUCCESS": s += 6
    if category == "Federal Policy": s += 5
    if category == "Academic Advising": s += 4
    if category == "AI in Higher Ed": s += 4
    for kw in ["community college","massachusetts","pell","workforce pell","fafsa","rulemaking","appropriation","ways and means","student success","transfer","ai"]:
        if kw in (text or "").lower():
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
    # Decode HTML entities (&nbsp;, &amp;, etc.)
    s = html.unescape(s or "")

    # Remove HTML tags
    s = re.sub(r"<[^>]+>", " ", s)

    # Replace non-breaking spaces
    s = s.replace("\xa0", " ")

    # Normalize whitespace
    s = normalize(s)

    return s[:n]

def inject_static_items(cfg: dict) -> List[dict]:
    out = []
    for a in cfg.get("static_items", []):
        out.append({"id": fingerprint(a["title"], a["url"]), "category": a["category"], "title": a["title"], "url": a["url"], "source": a.get("source", "Static"), "published": a.get("published", "N/A"), "summary": a.get("summary", ""), "why_it_matters": a.get("why_it_matters", ""), "tags": a.get("tags", []), "score": int(a.get("score", 10))})
    return out

def make_summary_for_brief(item: dict) -> str:
    base = (item.get("summary") or item.get("why_it_matters") or "").strip()
    if not base:
        return f"{item.get('title','This item')} surfaced in this run and scored highly for {item.get('category','higher ed')} relevance."
    return base

def make_why_it_matters(item: dict) -> str:
    existing = (item.get("why_it_matters") or "").strip()
    if existing:
        return existing
    cat = item.get("category", "")
    if cat == "MA Budget / SUCCESS":
        return "Potential implications for Massachusetts community-college funding, wraparound supports, transfer, or state-level student success work."
    if cat == "Federal Policy":
        return "Could affect aid eligibility, workforce programming, reporting, grants, or compliance planning."
    if cat == "Academic Advising":
        return "Relevant to advising practice, student persistence, retention strategy, or transfer support."
    if cat == "AI in Higher Ed":
        return "Relevant to AI governance, classroom use, advising operations, or institutional implementation."
    return "Potentially useful to community-college leaders and student-success practitioners."

def build_top_signals(items: List[dict]) -> List[dict]:
    return [{**it, "summary_for_brief": make_summary_for_brief(it), "why_it_matters": make_why_it_matters(it)} for it in sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:6]]

def build_briefing_notes(items: List[dict], cats: List[str]) -> List[dict]:
    notes = []
    for cat in cats:
        cat_items = [x for x in items if x.get("category") == cat]
        for it in sorted(cat_items, key=lambda x: x.get("score", 0), reverse=True)[:4]:
            notes.append({**it, "summary_for_brief": make_summary_for_brief(it), "why_it_matters": make_why_it_matters(it)})
    return notes

def build_linkedin_drafts(items: List[dict]) -> List[dict]:
    ordered = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    def top(cat):
        return next((x for x in ordered if x.get("category") == cat), None)
    ma = top("MA Budget / SUCCESS") or ordered[0]
    fed = top("Federal Policy") or ordered[min(1, len(ordered)-1)]
    ai = top("AI in Higher Ed") or top("Academic Advising") or ordered[min(2, len(ordered)-1)]
    return [
      {"title": "Massachusetts community college policy watch", "text": f"One Massachusetts item I’m tracking this week is {ma['title']} ({ma['url']}).\n\n{make_summary_for_brief(ma)}\n\nWhy it matters for community colleges: {make_why_it_matters(ma)}\n\n#Massachusetts #CommunityColleges #StudentSuccess #AcademicAdvising #HigherEdPolicy"},
      {"title": "Federal higher-ed policy watch", "text": f"A federal higher-ed item on my radar this week is {fed['title']} ({fed['url']}).\n\n{make_summary_for_brief(fed)}\n\nWhy it matters for community colleges: {make_why_it_matters(fed)}\n\n#HigherEdPolicy #CommunityColleges #FinancialAid #StudentSuccess #AcademicAdvising"},
      {"title": "AI in higher ed: practical implications", "text": f"One AI-in-higher-ed item I’m tracking this week is {ai['title']} ({ai['url']}).\n\n{make_summary_for_brief(ai)}\n\nWhy it matters for colleges: {make_why_it_matters(ai)}\n\n#AIinEducation #HigherEdLeadership #AcademicAdvising #StudentSuccess #EdTech"}
    ]

def write_rss(site_title: str, site_link: str, items: List[dict], out_path: Path, build_dt: datetime) -> None:
    now = build_dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    top = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:25]
    parts = ['<?xml version="1.0" encoding="UTF-8" ?>', '<rss version="2.0"><channel>', f"<title>{escape(site_title)}</title>", f"<link>{escape(site_link)}</link>", f"<description>{escape('Twice-weekly higher ed briefing.')}</description>", f"<lastBuildDate>{escape(now)}</lastBuildDate>"]
    for it in top:
        parts.append("<item>")
        parts.append(f"<title>{escape(it.get('title',''))}</title>")
        parts.append(f"<link>{escape(it.get('url',''))}</link>")
        parts.append(f"<guid>{escape(it.get('url',''))}</guid>")
        parts.append(f"<category>{escape(it.get('category',''))}</category>")
        desc = it.get("summary_for_brief") or it.get("summary") or it.get("why_it_matters") or ""
        parts.append(f"<description>{escape(desc[:900])}</description>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    out_path.write_text("\n".join(parts), encoding="utf-8")

def write_markdown(brief: dict, out_path: Path) -> None:
    lines = [f"# Higher Ed Intelligence Brief — Week of {brief['week_of']}", "", f"_Generated: {brief['generated_at']}_", "", "## LinkedIn-ready drafts", ""]
    for d in brief.get("linkedin_drafts", []):
        lines.extend([f"### {d.get('title','')}", "", d.get("text","").strip(), "", "---", ""])
    lines.extend(["## Top signals this run", ""])
    for it in brief.get("top_signals", []):
        lines.extend([f"### {it.get('title','')}", "", f"- Category: {it.get('category','')}", f"- Source: {it.get('source','')} ({it.get('published','N/A')})", f"- Link: {it.get('url','')}", f"- Summary: {it.get('summary_for_brief','')}", f"- Why it matters: {it.get('why_it_matters','')}", ""])
    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

def main() -> None:
    cfg = load_config()
    site = cfg["site"]
    filters = cfg["filters"]
    DATA.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    build_dt = now_et()
    cutoff = build_dt - timedelta(days=int(filters["days_lookback"]))
    items, seen_ids, feed_errors = [], set(), []
    for a in inject_static_items(cfg):
        if a["id"] not in seen_ids:
            items.append(a); seen_ids.add(a["id"])
    for feed in cfg.get("feeds", []):
        try:
            parsed = feedparser.parse(feed["url"])
            if getattr(parsed, "bozo", 0) and getattr(parsed, "bozo_exception", None):
                feed_errors.append(f"{feed.get('name','Feed')}: {parsed.bozo_exception}")
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
                it = {"id": fingerprint(title, link), "category": cat, "title": title, "url": link, "source": feed.get("name", "Feed"), "published": dt.strftime("%Y-%m-%d") if dt else "N/A", "summary": summary, "why_it_matters": "", "tags": [], "score": score(cat, hits, text)}
                if it["id"] in seen_ids:
                    continue
                items.append(it); seen_ids.add(it["id"])
        except Exception as exc:
            feed_errors.append(f"{feed.get('name','Feed')}: {exc}")
    max_total = int(filters["max_items_total"]); max_per_cat = int(filters["max_items_per_category"])
    cats = [r["category"] for r in cfg.get("category_rules", [])]
    kept = []
    for c in cats:
        cat_items = [x for x in items if x.get("category") == c]
        kept.extend(sorted(cat_items, key=lambda x: x.get("score", 0), reverse=True)[:max_per_cat])
    kept = sorted(kept, key=lambda x: x.get("score", 0), reverse=True)[:max_total]
    week = monday_of_week(build_dt.date()).isoformat()
    existing = sorted(ARCHIVE.glob("*.json"), reverse=True)[:16]
    archive_list = [{"label": f"Week of {p.stem}", "url": f"data/archive/{p.name}"} for p in existing]
    archive_list.insert(0, {"label": f"Week of {week}", "url": f"data/archive/{week}.json"})
    top_signals = build_top_signals(kept)
    briefing_notes = build_briefing_notes(kept, cats)
    linkedin_drafts = build_linkedin_drafts(top_signals if top_signals else kept)
    brief = {"schema_version": "2.0", "week_of": week, "generated_at": build_dt.strftime("%Y-%m-%d %H:%M ET"), "rss_url": "data/rss.xml", "categories": cats, "items": kept, "top_signals": top_signals, "briefing_notes": briefing_notes, "linkedin_drafts": linkedin_drafts, "archive": archive_list, "feed_errors": feed_errors}
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
