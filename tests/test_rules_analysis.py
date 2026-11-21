"""Tests the no-payment, no-LLM outage fallback against audited Titan odds."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import quality
import rules_analysis


def match(mid, total=2.5, opening=2.5):
    return {
        "id": str(mid), "league": "英超", "home": "伯恩茅斯",
        "away": "诺丁汉森林",
        "kickoff": "2026-11-21T23:00+08:00",
        "source_url": "https://zq.titan007.com/analysis/" + str(mid) + "cn.htm",
        "odds_checked_at": "2026-11-21T22:20:00+08:00",
        "asian_open": [0.82, 0.5, 0.93],
        "asian_live": [0.86, 0.5, 0.9],
        "euro_live": [1.88, 3.4, 4.5],
        "ou_open": [0.9, opening, 0.91],
        "ou_live": [0.85, total, 1.0],
    }


class RulesFallbackTests(unittest.TestCase):
    def test_produces_four_sourced_matches_with_three_scores(self):
        originals = [match(3003949 + i) for i in range(4)]
        generated = rules_analysis.build(originals)
        self.assertEqual(generated["analysis_engine"], "rules_fallback")
        self.assertEqual(len(generated["matches"]), 4)
        self.assertEqual(generated["matches"][0]["source_url"], originals[0]["source_url"])
        self.assertEqual(quality.safe_issues(generated, originals), [])
        for m in generated["matches"]:
            self.assertEqual(len(m["scores"]), 3)
            self.assertIn("规则", m["analysis"])

    def test_downward_line_and_under_score_consistency(self):
        originals = [match(3003949 + i, total=2.25, opening=2.75) for i in range(3)]
        generated = rules_analysis.build(originals)
        self.assertTrue(generated["matches"][0]["trend"].startswith("小 "))
        self.assertEqual(quality.safe_issues(generated, originals), [])

    def test_very_low_total_creates_no_fabricated_high_scores(self):
        # Most live football matches won't have such a low future pre-match line.
        # If too few possible scorelines exist, fail instead of fabricating.
        originals = [match(3003949 + i, total=0.5, opening=1.25) for i in range(3)]
        with self.assertRaises(ValueError):
            rules_analysis.build(originals)


if __name__ == "__main__":
    unittest.main()
