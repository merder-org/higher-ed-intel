#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
        "credit for prior learning",
        "prior learning assessment",
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
        "california",
        "governor",
        "budget",
        "appropriation",
        "student success",
        "transfer",
        "retention",
        "artificial intelligence",
        "credit for prior learning",
        "prior learning assessment",
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


def detect_story_tags(item: dict) -> List[str]:
    text = f"{item.get('title', '')} {item.get('summary', '')} {item.get('why_it_matters', '')}".lower()
    tags = []

    tag_rules = {
        "state_budget": [
            "governor",
            "budget",
            "appropriation",
            "state funding",
            "proposed budget",
            "investment",
        ],
        "credit_for_prior_learning": [
            "credit for prior learning",
            "prior learning assessment",
            "cpl",
            "pla",
        ],
        "artificial_intelligence_in_higher_ed": [
            "artificial intelligence",
            "generative ai",
            "chatgpt",
            "ai",
        ],
        "transfer_reform": [
            "transfer",
            "articulation",
            "credit mobility",
        ],
        "student_support_infrastructure": [
            "student success",
            "advising",
            "retention",
            "completion",
            "wraparound",
        ],
        "federal_rulemaking_or_grants": [
            "proposed rule",
            "final rule",
            "rulemaking",
            "federal register",
            "grant competition",
            "department of education",
            "department of labor",
            "grant",
        ],
    }

    for tag, keywords in tag_rules.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)

    return sorted(set(tags))


def needs_state_comparison(item: dict, target_state: str, comparative_mode: bool) -> bool:
    if not comparative_mode:
        return False

    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    source = (item.get("source") or "").lower()
    tags = detect_story_tags(item)

    if target_state.lower() in text:
        return False

    trigger_tags = {
        "state_budget",
        "credit_for_prior_learning",
        "artificial_intelligence_in_higher_ed",
        "transfer_reform",
        "student_support_infrastructure",
        "federal_rulemaking_or_grants",
    }

    if any(tag in trigger_tags for tag in tags):
        return True

    if "california" in text or "state" in source:
        return True

    return False


def build_comparison_points(item: dict, target_state: str) -> List[str]:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    points: List[str] = []

    if "california" in text:
        points.append(
            f"This appears to be a system-level initiative outside {target_state}, which makes it useful as a benchmark rather than just a local news item."
        )

    if "credit for prior learning" in text or "prior learning" in text or "cpl" in text:
        points.append(
            f"The underlying issue for {target_state} is whether community colleges are being given enough policy and operational support to scale credit for prior learning rather than treating it as a niche practice."
        )

    if "artificial intelligence" in text or " ai " in f" {text} ":
        points.append(
            f"For {target_state}, the more important question is not whether AI tools exist, but whether there is meaningful investment in governed, student-centered implementation."
        )

    if "budget" in text or "investment" in text or "appropriation" in text or "governor" in text:
        points.append(
            f"This can be framed as an investment comparison: what level of funding is another state prepared to put behind reform, and how does that compare with current commitments in {target_state}?"
        )

    if "grant" in text or "department of labor" in text or "department of education" in text:
        points.append(
            f"For {target_state}, the comparison question is whether colleges are positioned to capitalize on this kind of federal opportunity and whether state policy is helping them do so."
        )

    if not points:
        points.append(
            f"This story may offer a useful comparison point for policy and practice in {target_state}, especially if leaders are asking whether ambition is matched by implementation capacity."
        )

    return points


def build_core_story(item: dict, target_state: str, comparative_mode: bool) -> str:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

    if needs_state_comparison(item, target_state, comparative_mode):
        if "credit for prior learning" in text or "prior learning" in text or "cpl" in text:
            return (
                "This is not just a technology or innovation story. It is a public-investment story about whether a state is building enough system capacity to recognize learning, accelerate mobility, and modernize student pathways."
            )
        if "artificial intelligence" in text or " ai " in f" {text} ":
            return (
                "The deeper issue is whether institutions are moving from AI curiosity to real implementation supported by governance, staffing, and strategy."
            )
        if "budget" in text or "investment" in text or "appropriation" in text:
            return (
                "The core story here is about whether public policy is backing institutional expectations with real dollars and implementation capacity."
            )
        if "grant" in text or "rule" in text or "department of labor" in text or "department of education" in text:
            return (
                "The core story here is about whether colleges are ready to act on a major policy or funding shift before it becomes routine sector news."
            )

    cat = item.get("category", "")
    if cat == "MA Budget / SUCCESS":
        return "The core story is whether policy commitments are being matched by the student-support infrastructure needed to improve persistence and completion."
    if cat == "Federal Policy":
        return "The core story is how policy shifts translate into operational consequences for colleges and students."
    if cat == "AI in Higher Ed":
        return "The core story is whether colleges can define practical, governed uses of AI that actually strengthen teaching and student support."
    if cat == "Academic Advising":
        return "The core story is whether advising is being treated as institutional infrastructure rather than a reactive student-services function."

    return "The core story is the operational and strategic meaning of this development for community colleges."


def build_state_relevance(item: dict, target_state: str, comparative_mode: bool) -> str:
    if needs_state_comparison(item, target_state, comparative_mode):
        return (
            f"For {target_state}, the value of this story is comparative. It raises the question of whether community colleges are being funded and supported at a level that matches the expectations being placed on them."
        )

    return (
        f"This may be relevant to community-college leaders in {target_state} because it touches policy, advising, student support, transfer, or institutional operations."
    )


def build_recommended_angle(item: dict, target_state: str, comparative_mode: bool) -> str:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

    if needs_state_comparison(item, target_state, comparative_mode):
        if "credit for prior learning" in text or "prior learning" in text or "cpl" in text:
            return (
                f"Use this as a {target_state}-facing policy brief: if another large public system is investing in AI-enabled credit for prior learning, what would it take for {target_state} to build similar capacity?"
            )
        if "budget" in text or "investment" in text or "appropriation" in text:
            return (
                f"Frame this as an investment-gap question for {target_state}: are leaders expecting community colleges to do system-changing work without system-level funding?"
            )
        if "grant" in text or "rule" in text:
            return (
                f"Use this as an early signal: what would it take for community colleges in {target_state} to be ahead of this development rather than reacting to it later?"
            )
        return (
            f"Use this as a policy comparison story that helps leaders in {target_state} think about investment, implementation, and institutional capacity."
        )

    return "Use this as a straight higher-ed signal with practical implications for policy and operations."


def enrich_item(item: dict, target_state: str, comparative_mode: bool) -> dict:
    enriched = dict(item)
    enriched["summary_for_brief"] = make_summary_for_brief(item)
    enriched["why_it_matters"] = make_why_it_matters(item)
    enriched["story_tags"] = detect_story_tags(item)
    enriched["core_story"] = build_core_story(item, target_state, comparative_mode)
    enriched["state_relevance"] = build_state_relevance(item, target_state, comparative_mode)
    enriched["comparison_points"] = build_comparison_points(item, target_state) if needs_state_comparison(item, target_state, comparative_mode) else []
    enriched["recommended_angle"] = build_recommended_angle(item, target_state, comparative_mode)
    return enriched


def signal_priority(item: dict) -> int:
    text = f"{item.get('title','')} {item.get('summary','')} {item.get('source','')}".lower()
    s = int(item.get("score", 0))

    high_signal_terms = [
        "proposed rule",
        "final rule",
        "rulemaking",
        "federal register",
        "grant competition",
        "department of education",
        "department of labor",
        "appropriation",
        "budget",
        "ways and means",
        "massachusetts",
        "community college success fund",
        "success fund",
        "report",
        "initiative",
        "research",
        "survey",
        "policy",
        "guidance",
        "workforce pell",
        "grant",
    ]

    for term in high_signal_terms:
        if term in text:
            s += 3

    low_value_terms = [
        "podcast",
        "opinion",
        "event recap",
        "webinar",
        "sponsored",
        "advertisement",
    ]

    for term in low_value_terms:
        if term in text:
            s -= 3

    return s


def classify_signal_theme(item: dict) -> str:
    text = f"{item.get('title','')} {item.get('summary','')}".lower()

    if any(k in text for k in ["workforce pell", "short-term", "pell", "training grant", "department of labor", "workforce"]):
        return "Workforce Pell and short-term pathways"

    if any(k in text for k in ["7100-4002", "success fund", "massachusetts budget", "massdhe", "massachusetts", "appropriation"]):
        return "Massachusetts student success infrastructure"

    if any(k in text for k in ["advising", "advisor", "student success", "retention", "completion", "transfer", "holistic advising"]):
        return "Advising and student support"

    if any(k in text for k in ["artificial intelligence", "generative ai", "chatgpt", "edtech", "ai policy", "ai governance"]):
        return "AI implementation and governance"

    return "Other"


def build_signal_statement(theme: str, items: List[dict], target_state: str, comparative_mode: bool) -> dict:
    top = sorted(items, key=signal_priority, reverse=True)[0]
    enriched = enrich_item(top, target_state, comparative_mode)

    if theme == "Workforce Pell and short-term pathways":
        claim = "Federal policy is accelerating the shift toward short-term, workforce-aligned programs as a central community college strategy."
        implication = "Community colleges will need stronger advising, employer alignment, and outcomes reporting if they want to benefit from the next phase of federal support."
    elif theme == "Massachusetts student success infrastructure":
        claim = f"{target_state} is increasingly treating advising, transfer support, and wraparound services as core completion infrastructure rather than optional supports."
        implication = "The key question is no longer whether these supports matter, but whether colleges and the state can fund and scale them effectively."
    elif theme == "Advising and student support":
        claim = "Advising is emerging as a structural lever for completion, transfer, and workforce success—not just a student-services function."
        implication = "Colleges that treat advising as institutional infrastructure will be better positioned than those relying on fragmented or purely reactive models."
    elif theme == "AI implementation and governance":
        claim = "AI adoption in higher education is outpacing institutional clarity about governance, training, and appropriate use."
        implication = "The institutions that benefit most will be the ones that define clear use cases and guardrails before AI becomes embedded everywhere."
    else:
        claim = enriched["summary_for_brief"]
        implication = enriched["why_it_matters"]

    enriched["theme"] = theme
    enriched["claim"] = claim
    enriched["implication"] = implication
    return enriched


def build_signals(items: List[dict], target_state: str, comparative_mode: bool) -> List[dict]:
    themed: dict[str, List[dict]] = {}

    for item in items:
        theme = classify_signal_theme(item)
        if theme == "Other":
            continue
        themed.setdefault(theme, []).append(item)

    signals = []
    for theme, theme_items in themed.items():
        if theme_items:
            signals.append(build_signal_statement(theme, theme_items, target_state, comparative_mode))

    return sorted(signals, key=signal_priority, reverse=True)[:4]


def build_top_signals(items: List[dict], target_state: str, comparative_mode: bool) -> List[dict]:
    signals = build_signals(items, target_state, comparative_mode)
    if signals:
        return signals
    top = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:6]
    return [enrich_item(item, target_state, comparative_mode) for item in top]


def build_briefing_notes(items: List[dict], categories: List[str], target_state: str, comparative_mode: bool) -> List[dict]:
    notes: List[dict] = []
    for cat in categories:
        cat_items = [x for x in items if x.get("category") == cat]
        cat_items = sorted(cat_items, key=lambda x: x.get("score", 0), reverse=True)[:4]
        for item in cat_items:
            notes.append(enrich_item(item, target_state, comparative_mode))
    return notes


def select_feature_story(items: List[dict], target_state: str, comparative_mode: bool) -> Optional[dict]:
    candidates = [x for x in items if needs_state_comparison(x, target_state, comparative_mode)]
    if candidates:
        return sorted(candidates, key=signal_priority, reverse=True)[0]
    return None


def build_policy_comparison_draft(item: dict, target_state: str) -> dict:
    summary = item.get("summary_for_brief", "")
    core_story = item.get("core_story", "")
    state_relevance = item.get("state_relevance", "")
    why = item.get("why_it_matters", "")

    text = (
        f"One higher-ed development worth watching this week is {item['title']} ({item['url']}).\n\n"
        f"{summary}\n\n"
        f"What stands out to me is that {core_story}\n\n"
        f"For {target_state}, the key question is whether community colleges are being given the investment, staffing, and policy infrastructure needed to do similar work at scale.\n\n"
        f"Why this matters: {state_relevance} {why}\n\n"
        "That is where the real policy conversation should begin.\n\n"
        f"#{target_state.replace(' ', '')} #CommunityColleges #StudentSuccess #HigherEdPolicy #AcademicAdvising"
    )

    return {
        "title": f"{target_state} policy watch: a comparison worth making",
        "text": text,
        "source_item_id": item.get("id", ""),
        "draft_type": "policy_comparison",
    }


def build_linkedin_drafts(items: List[dict], target_state: str, comparative_mode: bool) -> List[dict]:
    ordered = sorted(items, key=signal_priority, reverse=True)

    if not ordered:
        return [
            {
                "title": "Weekly higher-ed signals",
                "text": (
                    "This week’s higher-ed signals are still taking shape.\n\n"
                    "I’m tracking developments in community college policy, advising, and AI in higher education, and I’ll be watching for the next round of concrete signals that affect student success and institutional planning.\n\n"
                    "#HigherEd #CommunityColleges #StudentSuccess #AcademicAdvising #AIinEducation"
                ),
                "draft_type": "fallback",
            }
        ]

    drafts: List[dict] = []

    feature = select_feature_story(ordered, target_state, comparative_mode)
    if feature:
        feature = enrich_item(feature, target_state, comparative_mode)
        drafts.append(build_policy_comparison_draft(feature, target_state))

    signals = build_signals(ordered, target_state, comparative_mode)
    if signals:
        for signal in signals[:3]:
            drafts.append(
                {
                    "title": signal["theme"],
                    "text": (
                        f"{signal['claim']}\n\n"
                        f"A good example is {signal['title']} ({signal['url']}). {signal['summary_for_brief']}\n\n"
                        f"What matters for community colleges is this: {signal['implication']}\n\n"
                        "That is where the real strategic question sits right now—not just what changed, but how institutions respond.\n\n"
                        + (
                            f"#{target_state.replace(' ', '')} #CommunityColleges #StudentSuccess #AcademicAdvising #HigherEdPolicy"
                            if signal["theme"] == "Massachusetts student success infrastructure"
                            else "#HigherEdPolicy #CommunityColleges #StudentSuccess #AcademicAdvising #EdTech"
                        )
                    ),
                    "source_item_id": signal.get("id", ""),
                    "draft_type": "signal_interpretation",
                }
            )
        return drafts[:4]

    def top(cat: str):
        return next((x for x in ordered if x.get("category") == cat), None)

    ma = enrich_item(top("MA Budget / SUCCESS") or ordered[0], target_state, comparative_mode)
    fed = enrich_item(top("Federal Policy") or top("Academic Advising") or ordered[min(1, len(ordered) - 1)], target_state, comparative_mode)
    ai = enrich_item(top("AI in Higher Ed") or ordered[min(2, len(ordered) - 1)], target_state, comparative_mode)

    drafts.append(
        {
            "title": f"{target_state} community college policy watch",
            "text": (
                f"One {target_state} development worth watching this week is {ma['title']} ({ma['url']}).\n\n"
                f"{ma.get('summary_for_brief', make_summary_for_brief(ma))}\n\n"
                "What stands out to me is that community college policy is increasingly about more than access alone. "
                "The deeper issue is whether institutions have enough advising, transfer, and wraparound-support capacity to convert access into persistence and completion.\n\n"
                f"Why this matters: {ma.get('why_it_matters', make_why_it_matters(ma))}\n\n"
                "For colleges, that is where the real work is.\n\n"
                f"#{target_state.replace(' ', '')} #CommunityColleges #StudentSuccess #AcademicAdvising #HigherEdPolicy"
            ),
            "source_item_id": ma.get("id", ""),
            "draft_type": "state_watch",
        }
    )

    drafts.append(
        {
            "title": "Federal higher-ed policy watch",
            "text": (
                f"A federal higher-ed development on my radar this week is {fed['title']} ({fed['url']}).\n\n"
                f"{fed.get('summary_for_brief', make_summary_for_brief(fed))}\n\n"
                "The most important thing about developments like this is not just the policy language itself. "
                "It is the operational effect on colleges: advising conversations, aid guidance, workforce programming, reporting obligations, and institutional planning.\n\n"
                f"Why this matters: {fed.get('why_it_matters', make_why_it_matters(fed))}\n\n"
                "Community colleges are often the institutions that feel these shifts first.\n\n"
                "#HigherEdPolicy #CommunityColleges #FinancialAid #StudentSuccess #AcademicAdvising"
            ),
            "source_item_id": fed.get("id", ""),
            "draft_type": "federal_watch",
        }
    )

    drafts.append(
        {
            "title": "AI in higher ed: practical implications",
            "text": (
                f"One AI-related higher-ed signal I’m tracking this week is {ai['title']} ({ai['url']}).\n\n"
                f"{ai.get('summary_for_brief', make_summary_for_brief(ai))}\n\n"
                "The real issue for colleges is not whether AI is coming. It is whether institutions can move beyond hype and define useful, governed, student-centered applications. "
                "That is especially important in advising, teaching, and student-support settings.\n\n"
                f"Why this matters: {ai.get('why_it_matters', make_why_it_matters(ai))}\n\n"
                "The colleges that benefit most will likely be the ones that combine experimentation with clear guardrails, staff development, and a strong sense of where human judgment still matters most.\n\n"
                "#AIinEducation #HigherEdLeadership #AcademicAdvising #StudentSuccess #EdTech"
            ),
            "source_item_id": ai.get("id", ""),
            "draft_type": "ai_watch",
        }
    )

    return drafts[:4]


def force_story_item(force_story_url: str, items: List[dict]) -> Optional[dict]:
    if not force_story_url:
        return None
    target = normalize(force_story_url)
    for item in items:
        if normalize(item.get("url", "")) == target:
            return item
    return None


def write_rss(site_title: str, site_link: str, items: List[dict], out_path: Path, build_dt: datetime) -> None:
    now = build_dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    top = sorted(items, key=signal_priority, reverse=True)[:25]

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
        f"_Target state: {brief.get('target_state', 'Massachusetts')}_",
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
                f"- Core story: {item.get('core_story', '')}",
                f"- State relevance: {item.get('state_relevance', '')}",
                f"- Recommended angle: {item.get('recommended_angle', '')}",
                f"- Why it matters: {item.get('why_it_matters', '')}",
                "",
            ]
        )

        comparison_points = item.get("comparison_points", [])
        if comparison_points:
            lines.append("- Comparison points:")
            for point in comparison_points:
                lines.append(f"  - {point}")
            lines.append("")

    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate higher-ed briefing.")
    parser.add_argument("--target-state", default="Massachusetts", help="Primary state lens for policy comparison.")
    parser.add_argument(
        "--comparative-mode",
        default="true",
        help="Enable comparative policy framing. Accepts true/false.",
    )
    parser.add_argument(
        "--force-story-url",
        default="",
        help="Optional: specific article URL to emphasize in the comparative story draft.",
    )
    return parser.parse_args()


def as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> None:
    args = parse_args()
    target_state = normalize(args.target_state) or "Massachusetts"
    comparative_mode = as_bool(args.comparative_mode)
    force_story_url = normalize(args.force_story_url)

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

    kept = sorted(kept, key=signal_priority, reverse=True)[:max_total]

    week = monday_of_week(build_dt.date()).isoformat()

    existing = sorted(ARCHIVE.glob("*.json"), reverse=True)[:16]
    archive_list = [{"label": f"Week of {p.stem}", "url": f"data/archive/{p.name}"} for p in existing]
    archive_list.insert(0, {"label": f"Week of {week}", "url": f"data/archive/{week}.json"})

    top_signals = build_top_signals(kept, target_state, comparative_mode)
    briefing_notes = build_briefing_notes(kept, categories, target_state, comparative_mode)

    forced = force_story_item(force_story_url, top_signals or kept)
    linkedin_drafts = build_linkedin_drafts(top_signals if top_signals else kept, target_state, comparative_mode)

    if forced:
        forced_enriched = enrich_item(forced, target_state, comparative_mode)
        forced_draft = build_policy_comparison_draft(forced_enriched, target_state)
        linkedin_drafts.insert(0, forced_draft)

    brief = {
        "schema_version": "4.0",
        "week_of": week,
        "generated_at": build_dt.strftime("%Y-%m-%d %H:%M ET"),
        "target_state": target_state,
        "comparative_mode": comparative_mode,
        "forced_story_url": force_story_url,
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

    write_rss(
        site["title"],
        site["public_base_url"].rstrip("/") + "/",
        top_signals if top_signals else kept,
        DATA / "rss.xml",
        build_dt,
    )

    print(f"OK: wrote latest.json + latest.md + archive/{week}.json + archive/{week}.md ({len(kept)} items).")
    print(f"Target state: {target_state} | Comparative mode: {comparative_mode}")
    if force_story_url:
        print(f"Forced story URL: {force_story_url}")
    if feed_errors:
        print("Feed warnings:")
        for err in feed_errors:
            print(f" - {err}")


if __name__ == "__main__":
    main()
