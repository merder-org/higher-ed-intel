"""Offline retrieval fixtures are illustrative, not live research findings."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import generate_weekly_brief as generator
from intelligence import (Page, PublicClient, canonical_url, discover_links,
                          evidence_fields, monitor_sources, page_item,
                          parse_date, priority_labels, publication_date, substantive)


def story(title, text, labels, score=30, source="Research"):
    return {"headline": title, "summary": text, "labels": labels, "score": score,
            "source": source, "id": title, "url": "https://example.org/" + title,
            "date": "2026-10-07", "published_dt": datetime(2026, 10, 7, tzinfo=generator.ET)}


class PriorityTests(unittest.TestCase):
    def test_explicit_advising_queries(self):
        for term in ("proactive advising", "case management", "guided pathways",
                     "advising caseloads", "early alerts", "transfer advising",
                     "AI in advising", "advising effectiveness"):
            with self.subTest(term=term):
                text = f"Community college research evaluates {term} and student persistence."
                self.assertIn("ADVISING", generator.extract_labels(text))
                self.assertTrue(substantive(story(term, text, ["ADVISING"])))

    def test_noise_does_not_get_topics_or_admission_from_source_name(self):
        for text in ("Investment advisor recommends an early college savings account.",
                     "President announces sports transfer completion rates.",
                     "Local hospital case management report.", "Farm workforce retention policy."):
            with self.subTest(text=text):
                self.assertNotIn("AI", generator.extract_labels(text))
                self.assertFalse(generator.should_keep_item(story(
                    text, text, [], source="Massachusetts Community College Advising Research")))
        self.assertNotIn("ADVISING", priority_labels("High school students receive early alerts for absences."))

    def test_boundary_matching_and_preserved_topics(self):
        self.assertNotIn("AI", generator.extract_labels("Community college enrollment climbs."))
        self.assertNotIn("TRANSFER", generator.extract_labels("College cryptographic ciphers improve."))
        self.assertIn("AI", generator.extract_labels("College tests LLM tools for academic advising."))
        text = "Massachusetts community college SUCCESS fund budget supports transfer, workforce and student success."
        for label in ("MASSACHUSETTS", "COMMUNITY COLLEGE", "TRANSFER", "WORKFORCE", "STUDENT SUCCESS", "POLICY"):
            self.assertIn(label, generator.extract_labels(text))

    def test_early_college_is_distinct_and_massachusetts_ranks_higher(self):
        summary = "Early College research evaluates dual enrollment credits and high school partnerships."
        national = story("Early College outcomes", summary, ["EARLY COLLEGE"])
        mass = story("Massachusetts Early College outcomes", summary, ["EARLY COLLEGE", "MASSACHUSETTS"])
        self.assertIn("EARLY COLLEGE", generator.extract_labels(summary))
        now = datetime(2026, 10, 8, tzinfo=generator.ET)
        self.assertGreater(generator.quality_score(mass, now, set()),
                           generator.quality_score(national, now, set()))

    def test_balancing_preserves_caps_and_rejects_thin_quota_items(self):
        advising = story("Proactive advising evaluation", "Community college randomized trial evaluates proactive advising and retention.", ["ADVISING"], 25, "CCRC")
        early = story("New Early College designation", "Massachusetts Early College partnership adds funded seats and college credits.", ["EARLY COLLEGE"], 24, "DESE")
        high = story("University governance", "University governance changes follow an announced board leadership decision.", ["GOVERNANCE"], 80, "News")
        thin = story("Advising event", "Academic advising matters for college students everywhere.", ["ADVISING"], 100, "Events")
        selected = generator.select_top_items([thin, high, advising, early], 3)
        self.assertIn(advising, selected)
        self.assertIn(early, selected)
        # Thin topic material can be general news, but cannot satisfy the reservation.
        self.assertEqual([], generator.select_top_items([high], 0))
        self.assertEqual([high], generator.select_top_items([high], 5))
        capped = generator.select_top_items([advising, {**early, "source": "CCRC"}, high], 5, per_source=1)
        self.assertEqual(1, sum(x["source"] == "CCRC" for x in capped))

    def test_evidence_and_limits_are_attributed_without_inventing_results(self):
        text = ("A randomized trial with 500 community college students evaluated proactive advising. "
                "The study found a 3 percentage points increase in persistence. "
                "A small sample limits generalizability.")
        signal = story("Advising study", text, ["ADVISING"])
        signal["evidence"] = evidence_fields(text)
        observation = generator.build_observation(signal)
        for token in ("randomized trial", "3 percentage points", "small sample", "editorial"):
            self.assertIn(token, observation)
        empty = generator.build_observation(story("Advising implementation",
            "Colleges introduce proactive advising outreach and report implementation activities.", ["ADVISING"]))
        self.assertIn("does not report a measurable", empty)
        self.assertIn("not specified", empty)

    def test_canonical_urls_do_not_drop_story_query_parameters(self):
        self.assertEqual("https://example.org/news?id=7",
                         canonical_url("https://example.org/news?id=7&utm_source=rss#section"))


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.source = {"name": "Fixture Research", "url": "https://example.org/publications",
                       "allowed_hosts": ["example.org"], "article_patterns": ["/publications/"],
                       "max_articles": 4}

    def article(self, title, body, date="2026-10-07"):
        return (f'<html><head><meta property="article:published_time" content="{date}">'
                f'<meta property="og:title" content="{title}"></head><body>'
                '<nav><p>Investment advisor sports report</p></nav>'
                f'<main><h1>{title}</h1><p>{body}</p></main>'
                '<footer><p>Copyright all rights reserved community college advising.</p></footer></body></html>')

    def test_public_page_retrieval_gets_both_subjects_and_filters_noise(self):
        listing = ('<a href="/publications/advising">Proactive advising research</a>'
                   '<a href="/publications/early">Early College study</a>'
                   '<a href="/publications/noise">Hospital case management</a>'
                   '<a href="https://outside.org/publications/early">Early College study</a>')
        pages = {
            self.source["url"]: listing,
            "https://example.org/publications/advising": self.article("Proactive advising evaluation",
                "A randomized trial of community college proactive advising found improved retention outcomes."),
            "https://example.org/publications/early": self.article("Early College partnership evaluation",
                "An Early College study evaluated high school and college partnerships and found increased credits."),
            "https://example.org/publications/noise": self.article("Hospital case management",
                "Hospital case management research found improved patient health outcomes in a randomized trial."),
        }

        class FakeClient:
            def read(self, url):
                return pages[url]

        warnings = []
        items = monitor_sources([self.source], warnings, client=FakeClient())
        self.assertEqual(2, len(items))
        self.assertEqual([], warnings)
        labels = {label for x in items for label in priority_labels(x["headline"] + " " + x["summary"])}
        self.assertEqual({"ADVISING", "EARLY COLLEGE"}, labels)
        self.assertNotIn("Copyright", items[0]["evidence_text"])
        self.assertNotIn("Investment", items[0]["evidence_text"])

    def test_date_published_beats_modified_and_copyright(self):
        page = Page('<script type="application/ld+json">{"@type":"ScholarlyArticle",'
                    '"datePublished":"2023-04-01","dateModified":"2026-10-07"}</script>'
                    '<footer>Copyright 2026</footer>')
        self.assertEqual("2023-04-01", publication_date(page).date().isoformat())
        self.assertIsNone(publication_date(Page('<meta property="article:modified_time" content="2026-10-07">')))
        self.assertIsNone(parse_date("June 2026"))
        self.assertIsNone(publication_date(Page("<p>Last Updated: June 3, 2026</p>")))
        dated = Page("<table><tr><td>Date:</td><td>June 3, 2026</td></tr></table>")
        self.assertEqual("2026-06-03", publication_date(dated).date().isoformat())

    def test_source_specific_month_dates_never_invent_publication_day(self):
        page = Page(self.article("Dual enrollment report",
            "Research from interviews found improved college partnership outcomes.", date=""))
        page.visible_text.extend(["Download Links", "Download working paper", "August 2026"])
        source = {**self.source, "month_date_pattern": r"Download Links.*?([A-Z][a-z]+ \d{4})"}
        value = page_item(page, source, "https://example.org/publications/dual")
        self.assertEqual("2026-08", value["publication_date"])
        self.assertEqual("month", value["date_precision"])
        self.assertIsNone(page_item(page, self.source, value["url"])["published_dt"])

    def test_robots_failure_and_deny_never_fetch_the_page(self):
        from urllib.robotparser import RobotFileParser
        client = PublicClient(["example.org"])
        deny = RobotFileParser()
        deny.parse(["User-agent: *", "Disallow: /"])
        client.robots["example.org"] = deny
        with self.assertRaises(ValueError):
            client.read("https://example.org/publications")
        self.assertFalse(client.allowed_host("https://outside.org/story"))
        self.assertFalse(client.allowed_host("http://example.org/story"))
        with patch.object(client, "read", side_effect=OSError("unavailable")):
            client.robots.clear()
            with self.assertRaises(ValueError):
                client.check_robots("https://example.org/story")

    def test_older_context_is_separate_in_markdown(self):
        brief = {"cycle_date": "2026-10-08", "generated_at": "now", "top_signals": [],
                 "pattern_this_cycle": "No fresh news.", "linkedin_angles": [], "watch_list": [],
                 "research_context": [{"headline": "Prior trial", "date": "2025-12-01",
                   "source": "Research", "summary": "Past findings.", "observation": "Limited sample.",
                   "url": "https://example.org/report"}]}
        md = generator.to_markdown(brief)
        self.assertIn("Older Research for Context", md)
        self.assertIn("Background research, published 2025-12-01", md)

    def test_full_generation_preserves_schema_and_separates_fresh_old_repeated_future(self):
        import tempfile
        from types import SimpleNamespace
        import validate_brief
        now = datetime(2026, 10, 8, 12, tzinfo=generator.ET)
        body = ("A randomized trial evaluated community college proactive advising. "
                "The study found increased persistence outcomes. A small sample limits generalizability.")

        def candidate(title, days, url):
            value = story(title, body, ["ADVISING"], source="Fixture Research")
            value.update(published_dt=now - timedelta(days=days), url=url,
                         evidence=evidence_fields(body), retrieval_method="public_html")
            return value

        fresh = candidate("Fresh advising evaluation", 1, "https://example.org/fresh")
        old = candidate("Prior advising trial", 30, "https://example.org/prior")
        repeated = candidate("Repeated advising evaluation", 1, "https://example.org/repeat?utm_source=new")
        future = candidate("Future advising evaluation", -1, "https://example.org/future")
        early = candidate("Massachusetts Early College partnership", 1, "https://example.org/early")
        early["summary"] = "A Massachusetts Early College partnership adds funded seats and college credits for high school students."
        early["evidence_text"] = early["summary"]
        early["evidence"] = evidence_fields(early["summary"])
        cfg = {"site": {}, "feeds": [], "monitored_sources": [],
               "filters": {"days_lookback": 5, "top_signals_max": 5}}
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            archive = data / "archive"
            archive.mkdir()
            (archive / "2026-10-06.json").write_text(json.dumps({
                "top_signals": [{"id": "previous-id", "url": "https://example.org/repeat"}]}), encoding="utf-8")
            with patch.object(generator, "DATA", data), patch.object(generator, "ARCHIVE", archive), \
                 patch.object(generator, "now_et", return_value=now), \
                 patch.object(generator, "load_config", return_value=cfg), \
                 patch.object(generator, "parse_args", return_value=SimpleNamespace(quiet=True, force_story_url="")), \
                 patch.object(generator, "monitor_sources", return_value=[fresh, old, repeated, future, early]):
                generator.main()
            output = json.loads((data / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual({"Fresh advising evaluation", "Massachusetts Early College partnership"},
                             {x["headline"] for x in output["top_signals"]})
            self.assertEqual(1, len(output["research_context"]))
            self.assertEqual("2026-09-08", output["research_context"][0]["date"])
            self.assertEqual({"ADVISING": 1, "EARLY COLLEGE": 1}, output["priority_coverage"])
            self.assertEqual("Monday / Wednesday / Friday", output["cadence"])
            with patch.object(validate_brief, "LATEST_JSON", data / "latest.json"):
                validate_brief.main()

    def test_config_keeps_existing_feeds_and_bounds_public_monitoring(self):
        cfg = json.loads(Path(generator.CFG_PATH).read_text(encoding="utf-8"))
        self.assertEqual(9, len(cfg["feeds"]))
        for source in cfg["monitored_sources"]:
            self.assertTrue(source["url"].startswith("https://"))
            self.assertLessEqual(source["max_articles"], 6)
            self.assertTrue(source["article_patterns"])


if __name__ == "__main__":
    unittest.main()
