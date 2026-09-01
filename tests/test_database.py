import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from db.database import DB_PATH, get_db_connection


class TestDatabase(unittest.TestCase):

    def setUp(self):
        """Create a temporary directory before each test for isolated DB operations."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = Path(self.temp_dir.name) / "data" / "target_products.db"

    def tearDown(self):
        """Clean up temporary files after each test."""
        self.temp_dir.cleanup()

    def test_get_db_connection_creates_dir_and_table(self):
        """Verify get_db_connection creates missing directories and initializes table schema."""
        with patch("db.database.DB_PATH", self.temp_db_path):
            conn = get_db_connection()

            # 1. Verify file and parent directory creation
            self.assertTrue(self.temp_db_path.parent.exists())
            self.assertTrue(self.temp_db_path.exists())

            # 2. Verify connection type
            self.assertIsInstance(conn, sqlite3.Connection)

            # 3. Verify target_products table exists in SQLite schema
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='target_products';"
            )
            result = cursor.fetchone()
            self.assertIsNotNone(result)
            self.assertEqual(result[0], "target_products")

            conn.close()

    def test_get_db_connection_idempotent(self):
        """Verify multiple calls do not raise errors when table already exists."""
        with patch("db.database.DB_PATH", self.temp_db_path):
            conn1 = get_db_connection()
            conn1.close()

            # Second call should safely execute CREATE TABLE IF NOT EXISTS without throwing exceptions
            try:
                conn2 = get_db_connection()
                conn2.close()
            except Exception as e:
                self.fail(f"get_db_connection raised an exception on repeated call: {e}")


if __name__ == "__main__":
    unittest.main()