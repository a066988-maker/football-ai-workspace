"""No-network regression checks for the free Gemini model fallback."""
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gemini_client


class DummyResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return io.BytesIO(self.data)

    def __exit__(self, *_):
        return None


class GeminiFallbackTests(unittest.TestCase):
    def setUp(self):
        gemini_client.LAST_WORKING = None

    def tearDown(self):
        gemini_client.LAST_WORKING = None

    def test_404_automatically_switches_to_supported_free_model(self):
        urls = []

        def mock_open(request, timeout):
            urls.append(request.full_url)
            if len(urls) == 1:
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
            return DummyResponse({"candidates": [{"content": {"parts": [{"text": '{"picks":[]}'}]}}]})

        with patch.dict(os.environ, {"GEMINI_API_KEY": "FAKE_TEST_ONLY", "GEMINI_MODEL": "gemini-3.5-flash-lite"}), \
             patch.object(gemini_client.urllib.request, "urlopen", side_effect=mock_open):
            data, model = gemini_client.call("hello")
        self.assertEqual(model, "gemini-3.8-flash")
        self.assertEqual(data, {"picks": []})
        self.assertEqual(len(urls), 2)
        self.assertIn("gemini-3.5-flash-lite", urls[0])
        self.assertIn("gemini-3.8-flash", urls[1])

    def test_retired_model_is_skipped(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-2.5-flash"}):
            self.assertNotIn("gemini-2.5-flash", gemini_client.candidate_models())

    def test_invalid_key_fails_closed_without_second_request(self):
        called = []
        def mock_open(request, timeout):
            called.append(1)
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "FAKE_TEST_ONLY", "GEMINI_MODEL": "gemini-3.5-flash-lite"}), \
             patch.object(gemini_client.urllib.request, "urlopen", side_effect=mock_open):
            with self.assertRaisesRegex(ValueError, "HTTP 403"):
                gemini_client.call("test")
        self.assertEqual(len(called), 1)


if __name__ == "__main__":
    unittest.main()
