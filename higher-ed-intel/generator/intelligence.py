"""Bounded public-page monitoring and evidence-grounded priority topics.

No paywall/login bypass, PDFs or JavaScript rendering. Failed/denied sources are
reported; missing publication dates never become fresh news.
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser

from dateutil import tz

ET = tz.gettz("America/New_York")
USER_AGENT = "HigherEdIntelBot/1.0"
PRIORITY_TOPICS = ("ADVISING", "EARLY COLLEGE")
# Explicit research/practice queries used to scan publication titles and content.
ADVISING_TERMS = (
    "academic advising", "proactive advising", "intrusive advising",
    "case management", "guided pathways", "advising caseloads",
    "early alerts", "early alert", "transfer advising", "AI in advising",
    "advising effectiveness", "advising", "academic advisor",
    "academic advisors", "student coaching",
)
EARLY_COLLEGE_TERMS = (
    "early college", "early-college", "dual enrollment", "dual enrolment",
    "dual enrolled", "dual-enrolled", "concurrent enrollment",
)
SCOPE_TERMS = (
    "college", "colleges", "university", "universities", "postsecondary",
    "higher education", "academic", "undergraduate", "students",
)
SUBSTANCE_TERMS = (
    "research", "study", "evaluation", "evaluated", "findings", "evidence",
    "trial", "survey", "interviews", "outcomes", "retention", "completion",
    "persistence", "graduation", "credits", "caseload", "caseloads",
    "implementation", "intervention", "outreach", "case management",
    "early alert", "early alerts", "funding", "grant", "grants",
    "budget", "designation", "designated", "partnership", "partnerships",
    "seats", "policy", "legislation", "training", "practice", "framework",
)
EXCLUDES = (
    "investment adviser", "investment advisor", "financial advisor",
    "financial adviser", "proxy advisors", "sports", "sponsored",
    "fraternity", "photo essay",
)


def has_term(text, terms):
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I)
               for term in terms)


def priority_labels(text):
    labels = []
    if has_term(text, SCOPE_TERMS):
        if has_term(text, ADVISING_TERMS) and has_term(text, SCOPE_TERMS[:-1]):
            labels.append("ADVISING")
        if has_term(text, EARLY_COLLEGE_TERMS):
            labels.append("EARLY COLLEGE")
    return labels


def in_scope(text):
    # A source name, "president", "transfer" or "completion" alone is not scope.
    return has_term(text, SCOPE_TERMS) or has_term(text, EARLY_COLLEGE_TERMS)


def substantive(item):
    text = item.get("headline", "") + " " + item.get("summary", "") + " " + item.get("evidence_text", "")
    return (bool(priority_labels(text)) and not has_term(text, EXCLUDES)
            and has_term(text, SUBSTANCE_TERMS) and len(item.get("summary", "")) >= 40)


def canonical_url(url):
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


class Page(HTMLParser):
    """Collect article paragraphs/metadata, excluding navigation and scripts."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.meta, self.links, self.paragraphs, self.dates, self.jsonld = {}, [], [], [], []
        self.stack, self.parts = [], []
        self.h1, self.title = "", ""
        self.visible_text = []
        self.href, self.anchor = None, []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append(tag)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
            if key and attrs.get("content"):
                self.meta[key.lower()] = attrs["content"]
        if attrs.get("itemprop") == "datePublished" and attrs.get("content"):
            self.dates.append(attrs["content"])
        if tag == "time" and attrs.get("datetime"):
            self.dates.append(attrs["datetime"])
        if tag == "a":
            self.href, self.anchor = attrs.get("href"), []
        if tag in {"p", "h1", "title"}:
            self.parts = []
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.parts = []
        if tag in {"meta", "link", "img", "br", "hr", "input", "source", "wbr", "area", "base", "embed", "param"}:
            self.stack.pop()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self.href is not None:
            self.anchor.append(data)
        if not any(tag in self.stack for tag in ("nav", "footer", "header", "style", "noscript")):
            self.parts.append(data)
            if "script" not in self.stack:
                self.visible_text.append(data)

    def handle_endtag(self, tag):
        text = re.sub(r"\s+", " ", " ".join(self.parts)).strip()
        if tag == "a" and self.href is not None:
            self.links.append((self.href, re.sub(r"\s+", " ", " ".join(self.anchor)).strip()))
            self.href = None
        if tag == "p" and not any(t in self.stack for t in ("nav", "footer", "header", "script")) and len(text) >= 40:
            self.paragraphs.append(text)
        elif tag == "h1":
            self.h1 = text
        elif tag == "title":
            self.title = text
        elif tag == "script":
            try:
                self.jsonld.append(json.loads("".join(self.parts)))
            except (ValueError, TypeError):
                pass
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]


def structured_articles(value):
    if isinstance(value, list):
        for child in value:
            yield from structured_articles(child)
    elif isinstance(value, dict):
        kind = value.get("@type", "")
        if isinstance(kind, str):
            kind = [kind]
        if set(kind) & {"Article", "NewsArticle", "ScholarlyArticle", "Report", "BlogPosting"}:
            yield value
        if "@graph" in value:
            yield from structured_articles(value["@graph"])


def parse_date(value):
    """Return exact publication date only; never infer day from a month/year."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}(?:T|$| )", value):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = None
            for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                return None
        return dt.replace(tzinfo=ET) if dt.tzinfo is None else dt.astimezone(ET)
    except (ValueError, TypeError):
        return None


def publication_date(page):
    for key in ("article:published_time", "citation_publication_date", "dc.date.issued", "datepublished"):
        dt = parse_date(page.meta.get(key))
        if dt:
            return dt
    for data in page.jsonld:
        for article in structured_articles(data):
            dt = parse_date(article.get("datePublished"))
            if dt:
                return dt
    # Only a single article-level time is safe; lists often contain many dates.
    if len(page.dates) == 1:
        return parse_date(page.dates[0])
    visible = re.sub(r"\s+", " ", " ".join(page.visible_text))
    # Explicit publication labels only; do not reinterpret copyright/Last Updated.
    match = re.search(r"(?:Publication Date|Date Published|Published|Date)\s*:\s*"
                      r"([A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2}/\d{1,2}/\d{4})", visible)
    return parse_date(match.group(1)) if match else None


def evidence_fields(text):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    patterns = {
        "findings": r"\b(found|findings|increased|reduced|improved|no effect|no impact|percentage points|associated|results|finds)\b",
        "methods": r"\b(randomized|randomised|trial|quasi-experimental|survey|interviews|sample|regression|longitudinal|synthesis)\b",
        "limitations": r"\b(limitation|limitations|cannot|could not|small sample|not statistically|not causal|generaliz[a-z]*|bundled)\b",
    }
    result = {}
    for field, pattern in patterns.items():
        hits = [sentence.strip() for sentence in sentences
                if 30 <= len(sentence.strip()) <= 700 and re.search(pattern, sentence, re.I)]
        result[field] = hits[:2]
    return result


class RestrictedRedirect(HTTPRedirectHandler):
    def __init__(self, client):
        self.client = client

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Validate every redirect before requesting it; never follow auth/off-domain redirects.
        if not self.client.allowed_host(newurl):
            raise ValueError("Redirect outside configured source hosts")
        if not urlsplit(newurl).path.endswith("/robots.txt"):
            self.client.check_robots(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PublicClient:
    def __init__(self, hosts):
        self.hosts = set(hosts)
        self.robots, self.last_request = {}, {}
        self.opener = build_opener(RestrictedRedirect(self))

    def allowed_host(self, url):
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname in self.hosts
                and not parts.username and not parts.password
                and parts.port in (None, 443))

    def read(self, url, robots=False):
        if not self.allowed_host(url):
            raise ValueError("URL outside configured HTTPS source hosts")
        if not robots:
            self.check_robots(url)
        host = urlsplit(url).netloc
        delay = 1.0
        policy = self.robots.get(host)
        if policy:
            delay = max(delay, policy.crawl_delay(USER_AGENT) or 0)
            rate = policy.request_rate(USER_AGENT)
            if rate and rate.requests:
                delay = max(delay, rate.seconds / rate.requests)
        time.sleep(max(0, delay - (time.monotonic() - self.last_request.get(host, 0))))
        self.last_request[host] = time.monotonic()
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"})
        with self.opener.open(request, timeout=15) as response:
            if not robots and response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
                raise ValueError("Only public HTML is monitored")
            content = response.read(2_000_001)
            if len(content) > 2_000_000:
                raise ValueError("Source exceeds 2 MB limit")
            return content.decode(response.headers.get_content_charset() or "utf-8", errors="replace")

    def check_robots(self, url):
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self.robots:
            # Fail closed on unavailable robots rather than assuming permission.
            self.robots[host] = RobotFileParser()
            try:
                body = self.read(f"https://{host}/robots.txt", robots=True)
                self.robots[host].parse(body.splitlines())
            except Exception:
                self.robots[host].parse(["User-agent: *", "Disallow: /"])
                raise ValueError("robots.txt unavailable; monitoring skipped")
        if not self.robots[host].can_fetch(USER_AGENT, url):
            raise ValueError("robots.txt disallows this resource")


def discover_links(page, source):
    found = []
    hosts = source["allowed_hosts"]
    patterns = source["article_patterns"]
    for href, title in page.links:
        url = canonical_url(urljoin(source["url"], href))
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in hosts:
            continue
        if not any(re.search(pattern, parts.path + ("?" + parts.query if parts.query else "")) for pattern in patterns):
            continue
        if (source.get("scan_all_matches") or has_term(title, ADVISING_TERMS + EARLY_COLLEGE_TERMS + tuple(source.get("discovery_terms", [])))) and url not in found:
            found.append(url)
    for url in source.get("seed_articles", []):
        url = canonical_url(url)
        if urlsplit(url).hostname in hosts and url not in found:
            found.append(url)
    return found[:source.get("max_articles", 6)]


def page_item(page, source, url):
    headline = page.meta.get("citation_title") or page.meta.get("og:title") or page.h1 or page.title
    description = page.meta.get("description") or page.meta.get("og:description") or ""
    # Use content, never menus/source branding, as the evidence corpus.
    paragraphs = page.paragraphs[:60]
    relevant = [p for p in paragraphs if has_term(p, ADVISING_TERMS + EARLY_COLLEGE_TERMS + SUBSTANCE_TERMS)]
    text = " ".join(relevant)[:18000]
    summary = (relevant[0] if relevant else description).strip()
    if len(summary) > 650:
        summary = summary[:650].rsplit(" ", 1)[0] + "..."
    published_dt = publication_date(page)
    precision = "day"
    date_label = published_dt.strftime("%Y-%m-%d") if published_dt else ""
    # Source-specific month labels remain month labels; the internal first-day
    # value is only an ordering bound and never qualifies as fresh news.
    if not published_dt and source.get("month_date_pattern"):
        visible = re.sub(r"\s+", " ", " ".join(page.visible_text))
        match = re.search(source["month_date_pattern"], visible, re.I)
        if match:
            try:
                published_dt = datetime.strptime(match.group(1), "%B %Y").replace(tzinfo=ET)
                precision, date_label = "month", published_dt.strftime("%Y-%m")
            except ValueError:
                pass
    return {
        "headline": html.unescape(headline).strip(),
        "summary": html.unescape(summary), "url": canonical_url(url),
        "source": source["name"], "published_dt": published_dt,
        "date_precision": precision, "publication_date": date_label,
        "evidence_text": text, "evidence": evidence_fields(text),
        "retrieval_method": "public_html",
    }


def monitor_sources(sources, warnings, client=None):
    hosts = {host for source in sources for host in source["allowed_hosts"]}
    client = client or PublicClient(hosts)
    items, seen = [], set()
    for source in sources:
        try:
            page = Page(client.read(source["url"]))
            urls = discover_links(page, source)
            if not urls:
                warnings.append(f"{source['name']}: no matching publication links in accessible HTML")
            for url in urls:
                if url in seen:
                    continue
                seen.add(url)
                try:
                    item = page_item(Page(client.read(url)), source, url)
                    if not item["published_dt"]:
                        warnings.append(f"{source['name']}: no exact publication date: {url}")
                        continue
                    if substantive(item):
                        items.append(item)
                except Exception as exc:
                    warnings.append(f"{source['name']}: {url}: {exc}")
        except Exception as exc:
            warnings.append(f"{source['name']}: {exc}")
    return items


def research_observation(item):
    evidence = item.get("evidence") or evidence_fields(item.get("summary", ""))
    parts = []
    for field, title in (("findings", "Source finding"), ("methods", "Method reported"),
                         ("limitations", "Source limitation")):
        hits = evidence.get(field, [])
        if hits:
            parts.append(f"{title}: {hits[0]}")
    if not evidence.get("findings"):
        parts.append("The accessible source does not report a measurable effectiveness finding.")
    if not evidence.get("methods"):
        parts.append("Study methods are not specified in the accessible text.")
    if not evidence.get("limitations"):
        parts.append("Study limitations are not specified in the accessible text; applicability needs checking.")
    if "EARLY COLLEGE" in item.get("labels", []):
        parts.append("Practical question (editorial): what do the reported changes require of high school/college partners, credit alignment and student supports?")
    else:
        parts.append("Practical question (editorial): how would the reported approach affect community college advising capacity, outreach and student outcomes?")
    return " ".join(parts)
