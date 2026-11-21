"""Offline safety tests: no live network calls, no Gemini quota used."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect
import analyze


class TitanParserTests(unittest.TestCase):
    def test_fixture_fields_and_time(self):
        fields = ["2906701", "1", "英超", "", "主队", "曼城", "", "客队",
                  "阿森纳", "", "", "2026,10,21,19,30,00", "",
                  "-1", "0", "0", "0", "0"]
        js = 'A[1]="' + "^".join(fields) + '".split(' + "'^'" + ');'
        items = collect.fixture_rows(js)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["home"], "曼城")
        self.assertEqual(items[0]["away"], "阿森纳")
        self.assertEqual(items[0]["kickoff"], "2026-11-21T19:30+08:00")
        self.assertEqual(items[0]["state"], -1)

    def test_odds_and_unavailable(self):
        js = ('sData[2906701]=['
              '[0.90,0.5,1.0,0.92,0.75,0.94],'
              '[2.2,3.4,3.2,2.1,3.5,3.1],'
              '[0.89,2.5,0.95,0.93,2.75,0.91],'
              '[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]];')
        parsed = collect.odds_rows(js)["2906701"]
        self.assertTrue(collect.usable_odds(parsed))
        self.assertEqual(parsed["ou_live"][1], 2.75)
        self.assertFalse(collect.usable_odds({"asian_open": [0.8, 0.5, 1]}))

    def test_browser_football_market_values(self):
        item = {
            "ID": "0_0_0_0", "homeOdds_f": "0.85", "letgoal_f": "半/一",
            "guestOdds_f": "0.85", "homeOdds": "0.68",
            "letgoal": "平/半", "guestOdds": "1.02",
            "upOdds_f": "0.88", "totalScore_f": "1.5",
            "downOdds_f": "0.82", "upOdds": "1.00",
            "totalScore": "0.5/1", "downOdds": "0.70",
        }
        market = collect.browser_market_rows([
            {"id": "3114415", "items": [item]}
        ])["3114415"]
        self.assertEqual(market["asian_open"], [0.85, 0.75, 0.85])
        self.assertEqual(market["asian_live"], [0.68, 0.25, 1.02])
        self.assertEqual(market["ou_live"], [1.0, 0.75, 0.7])
        market["euro_live"] = [1.26, 4.8, 6.7]
        self.assertTrue(collect.usable_odds(market))

    def test_invalid_fixtures_are_dropped(self):
        self.assertEqual(collect.fixture_rows("var A=[];"), [])
        self.assertEqual(collect.odds_rows("var sData=[];"), {})


class AiValidationTests(unittest.TestCase):
    def setUp(self):
        self.match = {
            "id": "2906701", "league": "英超", "home": "曼城",
            "away": "阿森纳", "kickoff": "2026-11-21T19:30+08:00",
            "source_url": "https://zq.titan007.com/analysis/2906701cn.htm",
            "odds_checked_at": "2026-11-21T16:00:00+08:00",
            "asian_open": [0.9, 0.5, 0.9], "asian_live": [0.9, 0.25, 0.9],
            "euro_live": [2.3, 3.2, 2.9], "ou_open": [0.9, 2.5, 0.9],
            "ou_live": [0.93, 2.75, 0.91],
        }

    def test_rejects_fake_totals(self):
        a = {"id": "2906701", "analysis": "此场盘口变化提示进球不确定性较大，需要谨慎观察。",
             "trend": "大 3.5", "scores": ["2-2", "3-1", "1-3"]}
        with self.assertRaisesRegex(ValueError, "invented"):
            analyze.validate_picks([self.match], {"picks": [a]})

    def test_accepts_consistent_pick(self):
        a = {"id": "2906701", "analysis": "此场盘口变化提示进球不确定性较大，需要谨慎观察。",
             "trend": "大 2.75", "scores": ["2-2", "3-1", "1-3"]}
        out = analyze.validate_picks([self.match], {"picks": [a]})
        self.assertEqual(out[0]["trend"], "大 2.75")
        self.assertEqual(out[0]["source_url"], self.match["source_url"])


if __name__ == "__main__":
    unittest.main()
