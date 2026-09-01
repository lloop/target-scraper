import json
import unittest
from unittest.mock import MagicMock, patch

from scraper.target_plp_scraper import (
    extract_tcins_from_plp,
    scrape_category_tcins,
)


class TestTargetPLPScraper(unittest.TestCase):

    def test_extract_tcins_from_plp(self):
        """Verify extraction of valid numeric TCIN strings from GraphQL raw response payload."""
        payload = {
            "data": {
                "search": {
                    "products": [
                        {"tcin": "12345678", "title": "Banana"},
                        {"tcin": "87654321", "title": "Apple"},
                        {"tcin": "invalid_tcin", "title": "Bad Product"},
                        {"tcin": None, "title": "No TCIN"},
                    ]
                }
            }
        }

        tcins = extract_tcins_from_plp(payload)

        self.assertEqual(len(tcins), 2)
        self.assertIn("12345678", tcins)
        self.assertIn("87654321", tcins)
        self.assertNotIn("invalid_tcin", tcins)

    @patch("scraper.target_plp_scraper.time.sleep")
    @patch("scraper.target_plp_scraper.sync_playwright")
    def test_scrape_category_tcins_success(self, mock_playwright, mock_sleep):
        """Verify end-to-end PLP TCIN harvest sequence with mocked browser network events."""
        # Setup mock playwright browser hierarchy
        mock_p = MagicMock()
        mock_playwright.return_value.__enter__.return_value = mock_p

        mock_browser = MagicMock()
        mock_p.chromium.launch.return_value = mock_browser

        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_page = MagicMock()
        mock_context.new_page.return_value = mock_page

        # Simulate network response capture for plp_search_v2
        def simulate_goto(url, **kwargs):
            # Trigger the 'on_response' callback registered via page.on("response", ...)
            callback = mock_page.on.call_args[0][1]
            mock_response = MagicMock()
            mock_response.url = "https://redsky.target.com/v1/plp_search_v2?key=value&category=123"
            mock_response.status = 200
            callback(mock_response)

        mock_page.goto.side_effect = simulate_goto

        # Mock page.evaluate fetch response for PLP search payload
        mock_payload = {
            "data": {
                "search": {
                    "products": [
                        {"tcin": "10000001"},
                        {"tcin": "10000002"},
                    ]
                }
            }
        }
        mock_page.evaluate.return_value = {
            "status": 200,
            "body": json.dumps(mock_payload),
        }

        tcins = scrape_category_tcins(
            category_url="https://www.target.com/c/produce-grocery/-/N-u7fty",
            target_count=2,
            store_id="3263",
            zip_code="19107",
        )

        # Assertions
        mock_page.goto.assert_called_once()
        self.assertEqual(len(tcins), 2)
        self.assertIn("10000001", tcins)
        self.assertIn("10000002", tcins)

    @patch("scraper.target_plp_scraper.sync_playwright")
    def test_scrape_category_tcins_throws_if_never_captured(self, mock_playwright):
        """Verify RuntimeError is raised if no 200 plp_search_v2 network request is observed."""
        mock_p = MagicMock()
        mock_playwright.return_value.__enter__.return_value = mock_p
        mock_browser = MagicMock()
        mock_p.chromium.launch.return_value = mock_browser
        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_page = MagicMock()
        mock_context.new_page.return_value = mock_page

        with self.assertRaises(RuntimeError) as ctx:
            scrape_category_tcins(
                category_url="https://www.target.com/c/produce-grocery/-/N-u7fty"
            )

        self.assertIn("Never observed a successful (200) plp_search_v2 request", str(ctx.exception))

    @patch("scraper.target_plp_scraper.time.sleep")
    @patch("scraper.target_plp_scraper.sync_playwright")
    def test_scrape_category_tcins_handles_backoff_and_retry(self, mock_playwright, mock_sleep):
        """Verify backoff loop executes on transient 502/503 server errors before succeeding."""
        mock_p = MagicMock()
        mock_playwright.return_value.__enter__.return_value = mock_p
        mock_browser = MagicMock()
        mock_p.chromium.launch.return_value = mock_browser
        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_page = MagicMock()
        mock_context.new_page.return_value = mock_page

        def simulate_goto(url, **kwargs):
            callback = mock_page.on.call_args[0][1]
            mock_response = MagicMock()
            mock_response.url = "https://redsky.target.com/v1/plp_search_v2?key=value"
            mock_response.status = 200
            callback(mock_response)

        mock_page.goto.side_effect = simulate_goto

        mock_payload = {"data": {"search": {"products": [{"tcin": "99999999"}]}}}

        # First attempt returns 502, second attempt returns 200 OK
        mock_page.evaluate.side_effect = [
            {"status": 502, "body": "Bad Gateway"},
            {"status": 200, "body": json.dumps(mock_payload)},
        ]

        tcins = scrape_category_tcins(
            category_url="https://www.target.com/c/test",
            target_count=1,
        )

        self.assertEqual(len(tcins), 1)
        self.assertIn("99999999", tcins)
        mock_sleep.assert_called()


if __name__ == "__main__":
    unittest.main()