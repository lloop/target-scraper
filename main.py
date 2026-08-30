import logging

from database.database import get_db_connection
from scraper.target_plp_scraper import scrape_category_tcins
from scraper.target_pdp_scraper import run_target_scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Config
TARGET_STORE_ID = "3991"
TARGET_ZIP_CODE = "44570"
CATEGORY_URL = "https://www.target.com/c/produce-grocery/-/N-u7fty"
TARGET_TCIN_COUNT = 50


def run_pipeline():
    logger.info("Starting Target extraction pipeline...")
    db_conn = get_db_connection()

    try:
        # Step 1: PLP Harvester
        tcins = scrape_category_tcins(
            category_url=CATEGORY_URL,
            target_count=TARGET_TCIN_COUNT,
            store_id=TARGET_STORE_ID,
            zip_code=TARGET_ZIP_CODE
        )

        if not tcins:
            logger.warning("No TCINs discovered. Exiting pipeline early.")
            return

        logger.info("Harvested %d TCINs. Executing PDP extraction...", len(tcins))

        # Step 2: PDP Extraction & Persistence
        run_target_scraper(
            tcin_list=tcins,
            db_conn=db_conn,
            store_id=TARGET_STORE_ID,
            zip_code=TARGET_ZIP_CODE
        )

        logger.info("Pipeline completed successfully.")

    except Exception as e:
        logger.error("Pipeline failure: %s", e, exc_info=True)
    finally:
        db_conn.close()


if __name__ == "__main__":
    run_pipeline()