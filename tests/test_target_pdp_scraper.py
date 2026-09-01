import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scraper.target_pdp_scraper import (
    block_unneeded_assets,
    extract_review_data,
    filter_tcins_needing_update,
    find_key_recursive,
    run_target_scraper,
    save_batch_to_sqlite,
    scrape_single_tcin,
)


class TestTargetPDPScraper(unittest.TestCase):

    def setUp(self):
        """Set up in-memory / temporary database for database operations."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"

        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(
            """
            CREATE TABLE target_products (
                tcin TEXT PRIMARY KEY,
                category TEXT,
                title TEXT,
                brand TEXT,
                price REAL,
                formatted_price TEXT,
                in_stock BOOLEAN,
                rating REAL,
                review_count INTEGER,
                primary_image TEXT,
                description TEXT,
                sample_reviews TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def tearDown(self):
        """Close DB connection and clean up temp files."""
        self.conn.close()
        self.temp_dir.cleanup()

    # --- Helper Utilities Tests ---

    def test_block_unneeded_assets(self):
        """Verify image, font, and stylesheet requests are aborted."""
        mock_route = MagicMock()

        # Test image route
        mock_route.request.resource_type = "image"
        block_unneeded_assets(mock_route)
        mock_route.abort.assert_called_once()

        # Test document route
        mock_route.reset_mock()
        mock_route.request.resource_type = "document"
        block_unneeded_assets(mock_route)
        mock_route.continue_.assert_called_once()

    def test_find_key_recursive(self):
        """Verify recursive searching through nested dicts and lists."""
        nested_data = {
            "a": 1,
            "b": [{"target": "found_1"}, {"c": 2}],
            "d": {"e": {"target": "found_2"}},
        }
        results = list(find_key_recursive(nested_data, "target"))
        self.assertEqual(results, ["found_1", "found_2"])

    def test_extract_review_data(self):
        """Verify extraction of review counts, ratings, and samples from __NEXT_DATA__."""
        sample_next_data = {
            "props": {
                "dehydratedState": {
                    "queries": [
                        {
                            "state": {
                                "data": {
                                    "data_source_modules": [
                                        {
                                            "module_data": {
                                                "data": {
                                                    "product": {
                                                        "ratings_and_reviews": {
                                                            "statistics": {
                                                                "rating": {
                                                                    "average": 4.5,
                                                                    "count": 10,
                                                                },
                                                                "review_count": 10,
                                                            },
                                                            "most_recent": [
                                                                {
                                                                    "author": {
                                                                        "nickname": "John"
                                                                    },
                                                                    "rating": {
                                                                        "value": 5,
                                                                        "submitted_at": "2026-01-01",
                                                                    },
                                                                    "title": "Great!",
                                                                    "text": "Loved it.",
                                                                }
                                                            ],
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            }
        }

        reviews = extract_review_data(sample_next_data)
        self.assertEqual(reviews["rating"], 4.5)
        self.assertEqual(reviews["review_count"], 10)
        self.assertEqual(len(reviews["sample_reviews"]), 1)
        self.assertEqual(reviews["sample_reviews"][0]["author"], "John")

    # --- DB Helpers Tests ---

    def test_save_batch_to_sqlite(self):
        """Verify batch inserts/UPSERT into SQLite database."""
        records = [
            {
                "tcin": "11111111",
                "category": "produce",
                "title": "Organic Bananas",
                "brand": "Good & Gather",
                "price": 1.99,
                "formatted_price": "$1.99",
                "in_stock": True,
                "rating": 4.8,
                "review_count": 50,
                "primary_image": "http://img.png",
                "description": "Fresh bananas",
                "sample_reviews": [{"author": "Bob", "rating": 5}],
            }
        ]

        save_batch_to_sqlite(self.conn, records)

        cursor = self.conn.cursor()
        cursor.execute("SELECT tcin, title, price FROM target_products WHERE tcin='11111111'")
        row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "11111111")
        self.assertEqual(row[1], "Organic Bananas")
        self.assertEqual(row[2], 1.99)

    def test_filter_tcins_needing_update(self):
        """Verify filtering out fresh TCINs while keeping new or stale TCINs."""
        # Insert one recent item into DB
        self.conn.execute(
            """
            INSERT INTO target_products (tcin, title, updated_at)
            VALUES ('FRESH1', 'Fresh Item', datetime('now'))
            """
        )
        self.conn.commit()

        tcin_list = ["FRESH1", "NEW1"]
        to_scrape = filter_tcins_needing_update(self.conn, tcin_list, max_age_days=7)

        self.assertIn("NEW1", to_scrape)
        self.assertNotIn("FRESH1", to_scrape)

    # --- Scraper Mock Tests ---

    def test_scrape_single_tcin_success(self):
        """Verify scrape_single_tcin parses DOM and __NEXT_DATA__ correctly."""
        mock_page = MagicMock()

        mock_dom_data = {
            "formatted_price": "$4.99",
            "image_url": "http://example.com/image.jpg",
            "rating_raw": "4.5",
            "reviews_raw": "20",
            "in_stock": True,
        }

        mock_next_data = {
            "product_description": {
                "title": "Test Product",
                "downstream_description": "A description",
            },
            "primary_brand": {"name": "Test Brand"},
        }

        # Setup mock returns
        mock_page.evaluate.side_effect = [mock_dom_data, mock_next_data]

        data = scrape_single_tcin(mock_page, "87654321")

        self.assertIsNotNone(data)
        self.assertEqual(data["tcin"], "87654321")
        self.assertEqual(data["title"], "Test Product")
        self.assertEqual(data["brand"], "Test Brand")
        self.assertEqual(data["price"], 4.99)
        self.assertEqual(data["formatted_price"], "$4.99")

    def test_scrape_single_tcin_unavailable_returns_none(self):
        """Verify empty page attributes trigger warning and return None."""
        mock_page = MagicMock()
        mock_page.evaluate.side_effect = [{"formatted_price": None, "in_stock": False}, {}]

        data = scrape_single_tcin(mock_page, "00000000")
        self.assertIsNone(data)

    @patch("scraper.target_pdp_scraper.time.sleep")
    @patch("scraper.target_pdp_scraper.scrape_single_tcin")
    @patch("scraper.target_pdp_scraper.sync_playwright")
    def test_run_target_scraper(self, mock_playwright, mock_scrape_single, mock_sleep):
        """Verify overall run_target_scraper flow, context initialization, and batching."""
        # Setup mock playwright browser context
        mock_p = MagicMock()
        mock_playwright.return_value.__enter__.return_value = mock_p
        mock_browser = MagicMock()
        mock_p.chromium.launch.return_value = mock_browser
        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_page = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_scrape_single.return_value = {
            "tcin": "12345",
            "title": "Mock Product",
            "brand": "Mock Brand",
            "price": 2.99,
            "formatted_price": "$2.99",
            "in_stock": True,
            "rating": 5.0,
            "review_count": 1,
            "primary_image": None,
            "description": None,
            "sample_reviews": [],
        }

        run_target_scraper(
            tcin_list=["12345"],
            category="produce",
            db_conn=self.conn,
            store_id="3263",
            zip_code="19107",
        )

        # Verify page requested scrape
        mock_scrape_single.assert_called_once()

        # Verify batch committed record into SQLite
        cursor = self.conn.cursor()
        cursor.execute("SELECT tcin, category FROM target_products WHERE tcin='12345'")
        row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "12345")
        self.assertEqual(row[1], "produce")


if __name__ == "__main__":
    unittest.main()