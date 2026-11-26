"""Regression tests using synthetic price rows; no networks or API keys."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import aiscore_backup


class BackupTests(unittest.TestCase):
    def test_same_book_open_and_current_and_formats(self):
        ident = "1234567890abcdef1234"
        data = {
            "eu": {ident: "1.40 4.33 6.50 1.36 5.00 8.50".split()},
            "ah": {ident: "-1/1.5 2.05 +1/1.5 1.80 -1.5 1.98 +1.5 1.88".split()},
            "ou": {ident: "2.5/3 1.98 1.88 3 2.00 1.85".split()},
        }
        result = aiscore_backup.complete_row(data)
        self.assertEqual(result["asian_open"], [1.05, -1.25, .80])
        self.assertEqual(result["ou_live"], [1, 3, .85])
        self.assertEqual(result["euro_open"], [1.40, 4.33, 6.50])
        data["ou"]["other"] = data["ou"].pop(ident)
        self.assertIsNone(aiscore_backup.complete_row(data))

    def test_reject_mislabelled_side_or_missing_snapshot(self):
        data = {"eu": {"book": "2 3 4 2 3 4".split()},
                "ah": {"book": "-1 1.97 -1 1.95 -1 1.98 +1 1.90".split()},
                "ou": {"book": "3 1.9 1.9 3 1.9 1.9".split()}}
        self.assertIsNone(aiscore_backup.complete_row(data))


if __name__ == "__main__":
    unittest.main()
