"""Prove the critique/rewrite/recheck loop actually retries and fails closed."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze


def fixture(mid):
    return {
        "id": str(mid), "league": "英超", "home": "曼城", "away": "富勒姆",
        "kickoff": "2026-11-21T20:30+08:00",
        "source_url": "https://zq.titan007.com/analysis/" + str(mid) + "cn.htm",
        "odds_checked_at": "2026-11-21T19:00:00+08:00",
        "asian_open": [0.8, 0.5, 0.95], "asian_live": [0.9, 0.5, 0.93],
        "euro_live": [2.1, 3.2, 3.4], "ou_open": [0.9, 2.5, 0.9],
        "ou_live": [0.88, 2.75, 0.91],
    }


def picks(bad=False):
    return {"picks": [{
        "id": str(2906701 + i),
        "analysis": "大小球盘口从二点五调整至二点七五，水位反映市场预期变化，但盘口不能保证进球数量，双方攻守节奏仍有不确定性。",
        "trend": "大 3.5" if bad else "大 2.75",
        "scores": ["2-1", "2-2", "3-1"],
    } for i in range(3)]}


class SelfRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.input = base / "input.json"
        self.output = base / "analysis.json"
        self.input.write_text(json.dumps({
            "source": "Titan007 live public football feed",
            "verified_at": "2026-11-21T19:00:00+08:00",
            "matches": [fixture(2906701 + i) for i in range(3)]
        }, ensure_ascii=False), encoding="utf-8")

    def test_incorrect_odds_are_rewritten_and_audited_again(self):
        with patch.object(analyze, "INPUT", self.input), patch.object(analyze, "OUTPUT", self.output), \
             patch.object(analyze, "gemini", side_effect=[picks(bad=True), picks()]) as generator, \
             patch.object(analyze, "ai_review", return_value=(True, [])):
            result = analyze.main()
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(generator.call_count, 2)
        self.assertEqual(len(result["repair_log"]), 1)
        self.assertIn("invented", result["repair_log"][0])
        data = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(data["self_check"]["independent_ai_review"], "passed")

    def test_independent_reviewer_can_force_rewrite(self):
        with patch.object(analyze, "INPUT", self.input), patch.object(analyze, "OUTPUT", self.output), \
             patch.object(analyze, "gemini", return_value=picks()) as generator, \
             patch.object(analyze, "ai_review", side_effect=[(False, ["风格需要修改"]), (True, [])]) as reviewer:
            result = analyze.main()
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(reviewer.call_count, 2)
        self.assertIn("风格需要修改", generator.call_args_list[1].kwargs["feedback"])

    def test_three_failed_rewrites_publish_nothing(self):
        with patch.object(analyze, "INPUT", self.input), patch.object(analyze, "OUTPUT", self.output), \
             patch.object(analyze, "gemini", return_value=picks(bad=True)) as generator:
            with self.assertRaisesRegex(ValueError, "failed"):
                analyze.main()
        self.assertEqual(generator.call_count, 3)
        self.assertFalse(self.output.exists())

    def test_auth_or_quota_error_stops_unbounded_retry(self):
        with patch.object(analyze, "INPUT", self.input), patch.object(analyze, "OUTPUT", self.output), \
             patch.object(analyze, "gemini", side_effect=ValueError("Gemini HTTP 429")) as generator:
            with self.assertRaisesRegex(ValueError, "HTTP 429"):
                analyze.main()
        self.assertEqual(generator.call_count, 1)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
