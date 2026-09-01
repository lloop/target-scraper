import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from main import run_pipeline


class TestMainPipeline(unittest.TestCase):

    def setUp(self):
        """Create a temporary database file for testing pipeline DB interactions."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = str(Path(self.temp_dir.name) / "test_target_products.db")

    def tearDown(self):
        """Clean up temporary directory after each test."""
        self.temp_dir.cleanup()

    @patch("main.run_target_scraper")
    @patch("main.filter_tcins_needing_update")
    @patch("main.scrape_category_tcins")
    def test_run_pipeline_full_execution(
        self, mock_plp_scrape, mock_filter, mock_pdp_scrape
    ):
        """Verify full execution path when TCINs are harvested and require PDP scraping."""
        mock_plp_scrape.return_value = ["12345678", "87654321"]
        mock_filter.return_value = ["12345678"]  # One TCIN needs scraping

        run_pipeline(
            category_url="https://www.target.com/test",
            category_name="test_category",
            target_count=10,
            db_path=self.temp_db_path
        )

        # 1. Verify PLP scraper called with correct kwargs
        mock_plp_scrape.assert_called_once_with(
            category_url="https://www.target.com/test",
            target_count=10,
            store_id="3263",
            zip_code="19107"
        )

        # 2. Verify filter called with connection and harvested TCINs
        mock_filter.assert_called_once()
        self.assertEqual(mock_filter.call_args[1]["tcin_list"], ["12345678", "87654321"])

        # 3. Verify PDP scraper executed for filtered TCIN
        mock_pdp_scrape.assert_called_once()
        self.assertEqual(mock_pdp_scrape.call_args[1]["tcin_list"], ["12345678"])

        # 4. Verify table schema was created in SQLite DB
        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='target_products';")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    @patch("main.run_target_scraper")
    @patch("main.filter_tcins_needing_update")
    @patch("main.scrape_category_tcins")
    def test_run_pipeline_empty_harvest_exits_early(
        self, mock_plp_scrape, mock_filter, mock_pdp_scrape
    ):
        """Verify pipeline exits early without touching database or running PDP scraper if PLP returns empty."""
        mock_plp_scrape.return_value = []

        run_pipeline(db_path=self.temp_db_path)

        mock_plp_scrape.assert_called_once()
        mock_filter.assert_not_called()
        mock_pdp_scrape.assert_not_called()

        # Verify DB file was not even created
        self.assertFalse(Path(self.temp_db_path).exists())

    @patch("main.run_target_scraper")
    @patch("main.filter_tcins_needing_update")
    @patch("main.scrape_category_tcins")
    def test_run_pipeline_all_tcins_up_to_date(
        self, mock_plp_scrape, mock_filter, mock_pdp_scrape
    ):
        """Verify PDP scraper is skipped if filter_tcins_needing_update returns an empty list."""
        mock_plp_scrape.return_value = ["12345678"]
        mock_filter.return_value = []  # All records up to date

        run_pipeline(db_path=self.temp_db_path)

        mock_plp_scrape.assert_called_once()
        mock_filter.assert_called_once()
        mock_pdp_scrape.assert_not_called()


if __name__ == "__main__":
    unittest.main()