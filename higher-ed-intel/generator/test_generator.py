from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo
import sys
import unittest


sys.modules.setdefault("feedparser", ModuleType("feedparser"))
dateutil_module = ModuleType("dateutil")
dateutil_module.tz = SimpleNamespace(
    UTC=timezone.utc,
    gettz=lambda name: ZoneInfo(name),
)
sys.modules.setdefault("dateutil", dateutil_module)
sys.modules.setdefault("dateutil.tz", dateutil_module.tz)


MODULE_PATH = Path(__file__).with_name("generate_weekly_brief.py")
SPEC = importlib.util.spec_from_file_location("brief_generator", MODULE_PATH)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def item(headline, source, summary, score, labels=None):
    return {
        "id": headline.lower().replace(" ", "-"),
        "headline": headline,
        "source": source,
        "summary": summary,
        "score": score,
        "labels": labels or ["COMMUNITY COLLEGE"],
        "date": "2026-08-07",
        "url": "https://example.org/story",
        "published_dt": datetime.now(generator.ET),
    }


class EditorialSelectionTests(unittest.TestCase):
    def test_noise_and_empty_summaries_are_rejected(self):
        self.assertFalse(generator.should_keep_item(item(
            "Headlines", "News", "A substantial higher education summary about colleges and policy.", 30
        )))
        self.assertFalse(generator.should_keep_item(item(
            "This week's poll: Pell plans", "News", "A substantial community college summary about Pell.", 30
        )))
        self.assertFalse(generator.should_keep_item(item(
            "College update", "News", "Too short", 30
        )))

    def test_selection_caps_sources_and_clusters_same_development(self):
        ranked = [
            item("Iowa gets Workforce Pell approval", "CCD", "Workforce Pell implementation reaches Iowa emergency programs.", 50),
            item("Nebraska prepares for Workforce Pell", "CCD", "Workforce Pell implementation reaches Nebraska colleges.", 48),
            item("Community college AI advising", "CCD", "A community college tests artificial intelligence in academic advising.", 45),
            item("Massachusetts transfer reform", "Mass DHE", "Massachusetts colleges simplify transfer pathways and advising.", 43),
            item("Student success redesign", "EDUCAUSE", "Colleges redesign student support using better data.", 40),
        ]
        selected = generator.select_top_items(ranked, limit=5, per_source=2)
        self.assertEqual(4, len(selected))
        self.assertEqual(2, sum(x["source"] == "CCD" for x in selected))
        self.assertEqual(1, sum("Workforce Pell" in x["headline"] for x in selected))

    def test_only_one_compact_linkedin_draft_is_generated(self):
        signal = item(
            "Advising reform cannot wait",
            "EAB",
            "Academic advisors face widening student readiness gaps and limited capacity.",
            40,
            ["ADVISING", "STUDENT SUCCESS"],
        )
        signal["observation"] = generator.build_observation(signal)
        angles = generator.build_linkedin_angles([signal], max_drafts=1)
        self.assertEqual(1, len(angles))
        self.assertNotIn("I've been thinking", angles[0]["draft"])
        self.assertLess(len(angles[0]["draft"]), 1200)


if __name__ == "__main__":
    unittest.main()
