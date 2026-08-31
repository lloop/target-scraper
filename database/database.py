import sqlite3
from pathlib import Path

# Saves to data/target_products.db at the project root
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "target_products.db"


def get_db_connection() -> sqlite3.Connection:
    """Returns an active SQLite connection and ensures the target_products table exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS target_products (
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn