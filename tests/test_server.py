import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from visualization.server import app


class TestServerAPI(unittest.TestCase):

    def setUp(self):
        """Set up Flask test client and a temporary database file."""
        self.app = app.test_client()
        self.app.testing = True

        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = str(Path(self.temp_dir.name) / "test_target_products.db")

        # Initialize temporary DB schema and insert mock product
        conn = sqlite3.connect(self.temp_db_path)
        conn.execute(
            """
            CREATE TABLE target_products (
                tcin TEXT PRIMARY KEY,
                title TEXT,
                category TEXT,
                price REAL,
                rating REAL,
                review_count INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO target_products (tcin, title, category, price, rating, review_count)
            VALUES ('12345678', 'Test Product', 'produce', 4.99, 4.5, 12)
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    @patch("visualization.server.DB_PATH")
    def test_get_products_success(self, mock_db_path):
        """Verify GET /api/products returns 200 OK and valid JSON rows."""
        # Replace server DB_PATH with our populated temporary DB
        with patch("visualization.server.DB_PATH", self.temp_db_path):
            response = self.app.get("/api/products")
            data = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["tcin"], "12345678")
            self.assertEqual(data[0]["price"], 4.99)

    @patch("visualization.server.DB_PATH")
    def test_get_products_db_not_found(self, mock_db_path):
        """Verify GET /api/products returns 404 when DB file does not exist."""
        missing_db_path = str(Path(self.temp_dir.name) / "missing.db")

        with patch("visualization.server.DB_PATH", missing_db_path):
            response = self.app.get("/api/products")
            data = response.get_json()

            self.assertEqual(response.status_code, 404)
            self.assertIn("error", data)
            self.assertIn("Database not found", data["error"])

    @patch("visualization.server.sqlite3.connect")
    def test_get_products_database_error(self, mock_connect):
        """Verify GET /api/products returns 500 on database query failure."""
        mock_connect.side_effect = sqlite3.OperationalError("Database disk image is malformed")

        with patch("visualization.server.DB_PATH", self.temp_db_path):
            response = self.app.get("/api/products")
            data = response.get_json()

            self.assertEqual(response.status_code, 500)
            self.assertIn("error", data)
            self.assertIn("Database disk image is malformed", data["error"])

    def test_cors_headers_present(self):
        """Verify CORS headers are returned on API endpoints."""
        with patch("visualization.server.DB_PATH", self.temp_db_path):
            response = self.app.get("/api/products")
            self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "*")


if __name__ == "__main__":
    unittest.main()