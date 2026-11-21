"""Regression tests for recursive quality gates; no network, no API keys."""
import copy
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import quality
import render

TAIPEI = ZoneInfo("Asia/Taipei")


def verified_fixture(mid, hour=20):
    return {
        "id": str(mid),
        "league": "英超",
        "home": "曼城",
        "away": "富勒姆",
        "kickoff": "2026-11-21T%02d:30+08:00" % hour,
        "source_url": "https://zq.titan007.com/analysis/" + str(mid) + "cn.htm",
        "odds_checked_at": "2026-11-21T19:10:00+08:00",
        "asian_open": [0.86, 0.75, 0.91],
        "asian_live": [0.90, 0.50, 0.90],
        "euro_live": [1.88, 3.45, 4.10],
        "ou_open": [0.9, 2.5, 0.94],
        "ou_live": [0.86, 2.75, 1.0],
    }


def analyzed_fixture(mid):
    m = verified_fixture(mid)
    m.update({
        "trend": "大 2.75",
        "scores": ["2-1", "3-1", "1-2"],
        "analysis": "本场大小球盘口由二点五球调整至二点七五球，进球预期有所变化。不过盘口变动无法保证赛果，主客两队仍需要根据临场比赛节奏决定攻守。",
    })
    return m


class QualityInputTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "source": "Titan007 live public football feed",
            "matches": [verified_fixture(str(2906701 + i)) for i in range(3)],
        }
        self.now = dt.datetime(2026, 11, 21, 19, 19, tzinfo=TAIPEI)

    def test_valid_source(self):
        issues = quality.input_issues(
            self.source, {"collection_method": "browser_loaded_public_source"},
            now=self.now,
        )
        self.assertEqual(issues, [])

    def test_espn_cannot_be_promoted_to_verified_titan(self):
        issues = quality.input_issues(
            self.source, {"collection_method": "espn_auxiliary_schedule_only"},
            now=self.now,
        )
        self.assertTrue(any("Titan" in error for error in issues))

    def test_rejects_stale_odds(self):
        source = copy.deepcopy(self.source)
        source["matches"][0]["odds_checked_at"] = "2026-11-20T12:00:00+08:00"
        issues = quality.input_issues(
            source, {"collection_method": "direct_public_feed"}, now=self.now,
        )
        self.assertTrue(any("fresh" in error for error in issues))

    def test_rejects_out_of_window_kickoff(self):
        source = copy.deepcopy(self.source)
        source["matches"][1]["kickoff"] = "2026-11-21T13:30+08:00"
        self.assertTrue(any("outside" in x for x in quality.input_issues(
            source, {"collection_method": "direct_public_feed"}, now=self.now
        )))


class OutputAuditTests(unittest.TestCase):
    def setUp(self):
        self.rows = [analyzed_fixture(str(2906701 + i)) for i in range(3)]
        self.original = [verified_fixture(str(2906701 + i)) for i in range(3)]

    def audit(self, rows=None):
        return quality.safe_issues({"matches": rows or self.rows}, self.original)

    def test_valid_rows(self):
        self.assertEqual(self.audit(), [])

    def test_detects_invented_odds(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["ou_live"][1] = 3.5
        issues = self.audit(rows)
        self.assertTrue(any("changed original ou_live" in x for x in issues))

    def test_detects_unsourced_injuries(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["analysis"] = "据悉球队主力缺阵，虽然没有进一步资料，但可能影响整体进攻安排。"
        self.assertTrue(any("unsupported" in x for x in self.audit(rows)))

    def test_detects_traditional_chinese(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["analysis"] = "這場賽事的關鍵點是進攻效率，雖然數據存在不確定性，但可以預測有一定節奏。"
        self.assertTrue(any("Traditional" in x for x in self.audit(rows)))

    def test_detects_conflicting_score(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["scores"] = ["1-0", "3-1", "1-2"]
        self.assertTrue(any("conflicts" in x for x in self.audit(rows)))

    def test_detects_bad_nested_scores_without_crashing(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["scores"] = [["2", "1"], "3-1", "1-2"]
        self.assertTrue(any("score" in x for x in self.audit(rows)))

    def test_assets_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            issues = quality.asset_issues(
                {"matches": self.rows}, base / "caption.txt", base / "poster.png"
            )
            self.assertTrue(any("missing" in x for x in issues))

    def test_caption_text_round_trip(self):
        text = render.post_text({"matches": self.rows})
        self.assertIn("比分：2-1 / 3-1 / 1-2", text)
        self.assertIn("趋势：大 2.75", text)
        self.assertIn("#足球", text)

    def test_rejects_wrong_image_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "caption.txt").write_text(
                render.post_text({"matches": self.rows}), encoding="utf-8"
            )
            bad_png = quality.PNG_SIG + b"\x00" * 8 + b"\x00\x00\x04\x00\x00\x00\x04\x00" + b"0" * 12000
            (base / "poster.png").write_bytes(bad_png)
            issues = quality.asset_issues(
                {"matches": self.rows}, base / "caption.txt", base / "poster.png"
            )
            self.assertTrue(any("1080x1920" in x for x in issues))


if __name__ == "__main__":
    unittest.main()
