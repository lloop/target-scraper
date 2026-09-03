import sqlite3
import logging

from scraper.target_plp_scraper import scrape_category_tcins
from scraper.target_pdp_scraper import run_target_scraper, filter_tcins_needing_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TargetPipeline") 

# --- PIPELINE CONFIGURATION ---
CATEGORY_URL = "https://www.target.com/c/produce-grocery/-/N-u7fty"
CATEGORY_NAME = "produce"
TARGET_TCIN_COUNT = 0   # Set to 0 to scrape the entire category
STORE_ID = "1443" 
ZIP_CODE = "19148"
DB_PATH = "data/target_products.db"
MAX_STALE_DAYS = 30

CATEGORIES = [
    {"name": "produce", "url": "https://www.target.com/c/produce-grocery/-/N-u7fty"},
    {"name": "bakery", "url": "https://www.target.com/c/bakery-bread-grocery/-/N-5xt19"},
    {"name": "snacks", "url": "https://www.target.com/c/snacks-grocery/-/N-5xsy9"},
    {"name": "frozen", "url": "https://www.target.com/c/frozen-foods-grocery/-/N-5xszd"},
    {"name": "meat", "url": "https://www.target.com/c/fresh-meat-seafood-grocery/-/N-5xsyh"},
    {"name": "beverages", "url": "https://www.target.com/c/beverages-grocery/-/N-5xt0r"},
    {"name": "pantry", "url": "https://www.target.com/c/pantry-grocery/-/N-5xt13"},
]


def run_pipeline(
    category_url: str = CATEGORY_URL,
    category_name: str = CATEGORY_NAME,
    target_count: int = TARGET_TCIN_COUNT,
    store_id: str = STORE_ID,
    zip_code: str = ZIP_CODE,
    db_path: str = DB_PATH,
    max_stale_days: int = MAX_STALE_DAYS
):
    """Executes the complete Target extraction pipeline."""
    logger.info("Initializing Target Scraper Pipeline...")
    
    # --- PHASE 1: Headed PLP Extraction ---
    logger.info("Phase 1: Starting PLP TCIN harvest (Headed Mode)...")
    tcins = scrape_category_tcins(
        category_url=category_url,
        target_count=target_count,
        store_id=store_id,
        zip_code=zip_code
    )
    logger.info("Harvested %d TCINs from PLP.", len(tcins))

    if not tcins:
        logger.warning("No TCINs were harvested. Exiting pipeline early.")
        return

    # --- PHASE 2: Database Setup & Deduplication ---
    logger.info("Phase 2: Connecting to SQLite database (%s)...", db_path)
    db_conn = sqlite3.connect(db_path)
    
    # Ensure standard schema exists
    with db_conn:
        db_conn.execute("""
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

    # Filter out fresh records
    tcins_to_scrape = filter_tcins_needing_update(
        db_conn=db_conn, 
        tcin_list=tcins, 
        max_age_days=max_stale_days
    )
    logger.info("TCINs requiring full PDP extraction: %d", len(tcins_to_scrape))

    # --- PHASE 3: Headless PDP Batch Extraction ---
    if tcins_to_scrape:
        logger.info("Phase 3: Starting PDP detail scraper (Headless Mode)...")
        run_target_scraper(
            tcin_list=tcins_to_scrape,
            category=category_name,
            db_conn=db_conn,
            store_id=store_id,
            zip_code=zip_code
        )
    else:
        logger.info("All harvested TCINs are up to date in DB. No PDP scraping required.")

    db_conn.close()
    logger.info("Pipeline execution finished successfully.")


if __name__ == "__main__":
    for cat in CATEGORIES:
        logger.info("Processing category: %s", cat["name"])
        run_pipeline(
            category_url=cat["url"],
            category_name=cat["name"]
        )