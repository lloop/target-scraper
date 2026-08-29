import logging
from database.database import get_db_connection
from scraper.target_plp_scraper import scrape_category_tcins
from scraper.target_pdp_scraper import run_target_scraper

logging.basicConfig(
level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],  # Forces stream output to console
    force=True
)

def main():
    # 1. Target category or search listing URL (PLP)
    category_url = "https://www.target.com/c/produce-grocery/-/N-u7fty"

    # 2. Discover list of TCINs from category level
    logging.info("Extracting TCIN catalog from PLP: %s", category_url)
    tcins_to_scrape = scrape_category_tcins(category_url, target_count=20)

    if not tcins_to_scrape:
        logging.warning("No TCINs were discovered from the category page. Exiting pipeline.")
        return

    logging.info("Discovered %d unique TCIN(s) to scrape.", len(tcins_to_scrape))

    # 3. Open DB connection and process product detail pages (PDP)
    logging.info("Opening database connection...")
    db_conn = get_db_connection()

    try:
        logging.info("Starting PDP scraper engine for %d item(s)...", len(tcins_to_scrape))
        run_target_scraper(tcins_to_scrape, db_conn)
    finally:
        db_conn.close()
        logging.info("Database connection closed. Pipeline complete.")


if __name__ == "__main__":
    main()