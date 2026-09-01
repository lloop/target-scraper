import logging
from database.database import get_db_connection
from scraper.target_plp_scraper import scrape_category_tcins
from scraper.target_pdp_scraper import (
    run_target_scraper,
    filter_tcins_needing_update,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Config
# Target Philadelphia Snyder Ave - 1443
TARGET_STORE_ID = "1443" 
TARGET_ZIP_CODE = "19148"
TARGET_TCIN_COUNT = 0
# CATEGORIES = [
#     {"name": "produce", "url": "https://www.target.com/c/produce-grocery/-/N-u7fty"},
# ]
CATEGORIES = [
    {"name": "produce", "url": "https://www.target.com/c/produce-grocery/-/N-u7fty"},
    {"name": "bakery", "url": "https://www.target.com/c/bakery-bread-grocery/-/N-5xt19"},
    {"name": "snacks", "url": "https://www.target.com/c/snacks-grocery/-/N-5xsy9"},
    {"name": "frozen", "url": "https://www.target.com/c/frozen-foods-grocery/-/N-5xszd"},
    {"name": "meat", "url": "https://www.target.com/c/fresh-meat-seafood-grocery/-/N-5xsyh"},
    {"name": "beverages", "url": "https://www.target.com/c/beverages-grocery/-/N-5xt0r"},
    {"name": "pantry", "url": "https://www.target.com/c/pantry-grocery/-/N-5xt13"},
]


def run_pipeline(category):
    logger.info("Starting Target extraction pipeline...")
    db_conn = get_db_connection()

    try:
        # Step 1: PLP Harvester
        tcins = scrape_category_tcins(
            category_url=category["url"],
            target_count=TARGET_TCIN_COUNT,
            store_id=TARGET_STORE_ID,
            zip_code=TARGET_ZIP_CODE
        )

        if not tcins:
            logger.warning("No TCINs discovered. Exiting pipeline early.")
            return
        
        logger.info("Harvested %d TCINs. Checking database freshness...", len(tcins))

        tcins_to_scrape = filter_tcins_needing_update(
            db_conn=db_conn,
            tcin_list=tcins,
            max_age_days=30,
        )

        if not tcins_to_scrape:
            logger.info("All harvested TCINs were updated within the last 30 days. Nothing to scrape.")
            return

        logger.info(
            "Filtered %d TCINs down to %d that need scraping.",
            len(tcins),
            len(tcins_to_scrape),
        )

        logger.info("Harvested %d TCINs. Executing PDP extraction...", len(tcins))

        # Step 2: PDP Extraction & Persistence
        run_target_scraper(
            tcin_list=tcins_to_scrape,
            db_conn=db_conn,
            category=category["name"],
            store_id=TARGET_STORE_ID,
            zip_code=TARGET_ZIP_CODE
        )

        logger.info("Pipeline completed successfully.")

    except Exception as e:
        logger.error("Pipeline failure: %s", e, exc_info=True)
    finally:
        db_conn.close()


if __name__ == "__main__":
    import time
    import random

    for idx, cat in enumerate(CATEGORIES, 1):
        logger.info(f"Starting scrape for category [{idx}/{len(CATEGORIES)}]: {cat['name']}")
        run_pipeline(cat)
        
        # Take a 2 to 3 minute pause before starting the next category
        if idx < len(CATEGORIES):
            cooldown = random.uniform(120, 180)
            logger.info(f"Category complete. Cooling down for {int(cooldown)}s before next category...")
            time.sleep(cooldown)