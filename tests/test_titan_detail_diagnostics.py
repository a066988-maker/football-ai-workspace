"""Diagnostic checks must not publish or read hidden market cells."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect


def page_stub(preferred=0, fallback=0, visible=True, wall=False):
    page = Mock()
    prompt = page.get_by_text.return_value
    prompt.count.return_value = int(wall)
    prompt.first.is_visible.return_value = wall
    rows, generic = Mock(), Mock()
    page.locator.side_effect = lambda selector: rows if selector == "tr" else generic
    crow = rows.filter.return_value
    crow.count.return_value = preferred
    generic.count.return_value = fallback
    selected = crow.first if preferred else generic.first
    selected.is_visible.return_value = visible
    selected.locator.return_value.all_inner_texts.return_value = [" 1.55 ", "3.20"]
    return page, selected


class DetailDiagnosticsTests(unittest.TestCase):
    def test_registration_wall_never_reads_market_rows(self):
        page, _ = page_stub(preferred=4, wall=True)
        self.assertEqual(collect.inspect_detail_row(page, "euro"), (None, {"outcome": "registration_wall"}))
        page.locator.assert_not_called()

    def test_missing_rows_are_distinct_from_hidden(self):
        page, _ = page_stub()
        self.assertEqual(collect.inspect_detail_row(page, "euro")[1]["outcome"], "row_missing")
        page, hidden = page_stub(preferred=2, fallback=4, visible=False)
        info = collect.inspect_detail_row(page, "euro")[1]
        self.assertEqual((info["outcome"], info["preferred_rows"], info["fallback_rows"]),
                         ("first_row_hidden", 2, 4))
        hidden.locator.assert_not_called()

    def test_visible_parse_rejection_and_success_are_distinct(self):
        page, _ = page_stub(fallback=4)
        with patch.object(collect, "detail_market", side_effect=[None, {"euro_live": [1.55, 3.2, 4.1]}]) as parse:
            self.assertEqual(collect.inspect_detail_row(page, "euro")[1]["outcome"], "parser_rejected_visible_row")
            parsed, report = collect.inspect_detail_row(page, "euro")
            self.assertIn("euro_live", parsed)
            self.assertEqual((report["selector"], report["cell_count"], report["outcome"]), ("fallback", 2, "parsed"))
            parse.assert_called_with("euro", ["1.55", "3.20"])
