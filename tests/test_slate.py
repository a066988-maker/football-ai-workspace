"""Regression coverage for late scheduled retries spanning Taipei midnight."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect
import daily
import quality
from slate import ZONE, slate_window
from test_quality import verified_fixture


def local(hour, minute=0):
    return dt.datetime(2026, 11, 27, hour, minute, tzinfo=ZONE)


class SlateTests(unittest.TestCase):
    def test_midnight_retry_and_exact_morning_boundary(self):
        earlier, cutoff = slate_window(local(2))
        self.assertEqual(earlier.isoformat(), "2026-11-26T16:00:00+08:00")
        self.assertEqual(cutoff, local(8))
        self.assertEqual(slate_window(local(7, 59))[0], earlier)
        self.assertEqual(slate_window(local(8))[0], local(16))
        self.assertEqual(slate_window(local(16))[0], local(16))
        self.assertEqual(slate_window(local(2).astimezone(dt.timezone.utc)), (earlier, cutoff))

    def test_collect_writes_previous_evening_slate_after_midnight(self):
        fixture = {"id": "1", "league": "联赛", "state": -1, "kickoff": local(4).isoformat()}
        next_slate = dict(fixture, id="2", kickoff=local(21).isoformat())
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            with patch.multiple(collect, OUT=out, DATA=out / "data"), \
                 patch.object(collect, "fetch", side_effect=OSError("offline test")), \
                 patch.object(collect, "dated_schedule", return_value=([fixture, next_slate], {})) as dated, \
                 patch.object(collect, "browser_source", return_value=([], {}, {})), \
                 patch("builtins.print"):
                report = collect.collect(now=local(2))
            dated.assert_called_once_with(*slate_window(local(2)))
            self.assertEqual(report["window_fixture_count"], 1)
            self.assertEqual(report["complete_odds_count"], 0)
            data = json.loads((out / "fixtures.json").read_text())
            self.assertEqual(data["date"], "2026-11-26")
            self.assertEqual([m["id"] for m in data["fixtures"]], ["1"])

    def test_quality_accepts_only_the_same_overnight_slate(self):
        matches = [
            dict(verified_fixture(2906701 + i),
                 kickoff=local(4, i).isoformat(), odds_checked_at=local(2).isoformat())
            for i in range(3)
        ]
        data = {"source": "Titan007 live public football feed", "matches": matches}
        status = {"collection_method": "direct_public_feed"}
        self.assertEqual(quality.input_issues(data, status, now=local(2)), [])
        matches[0]["kickoff"] = local(21).isoformat()
        self.assertTrue(any("outside" in issue for issue in quality.input_issues(data, status, now=local(2))))

    def test_verified_artifacts_are_retained_on_late_retry(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "status.json").write_text(json.dumps({
                "status": "analysis_ready_rules", "window_start": "2026-11-26T16:00+08:00",
            }))
            (out / "analysis.json").write_text('{"analysis_engine":"rules_fallback","matches":[]}')
            (out / "qa_report.json").write_text('{"status":"passed","publish_allowed":true}')
            (out / "poster.png").touch()
            (out / "xiaohongshu.txt").touch()
            with patch.object(daily, "OUT", out), \
                 patch.object(quality, "full_odds_sop_issues", return_value=[]), \
                 patch.object(quality, "safe_issues", return_value=[]), \
                 patch.object(quality, "asset_issues", return_value=[]), \
                 patch.object(daily.dt, "datetime", wraps=dt.datetime) as clock, \
                 patch.object(collect, "collect") as run_collect, \
                 patch("builtins.print"):
                clock.now.return_value = local(2)
                daily.main()
                run_collect.assert_not_called()
                self.assertTrue((out / "poster.png").exists())
                self.assertFalse(daily.already_complete_slate(local(8)))
