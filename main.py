import logging
from database.database import get_db_connection
from scraper.target_pdp_scraper import run_target_scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def main():
    # Provide test TCINs to process
    tcins_to_scrape = ["15013944"]

    logging.info("Opening database connection...")
    db_conn = get_db_connection()

    try:
        logging.info("Starting scraper engine for %d TCIN(s)...", len(tcins_to_scrape))
        run_target_scraper(tcins_to_scrape, db_conn)
    finally:
        db_conn.close()
        logging.info("Database connection closed. Pipeline complete.")


if __name__ == "__main__":
    main()