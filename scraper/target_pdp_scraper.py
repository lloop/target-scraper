import os
import re
import json
import logging
import time
from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
REQUEST_DELAY = 0.5

INTERSECTION_SCRIPT = """
    const OriginalObserver = window.IntersectionObserver;
    window.IntersectionObserver = class extends OriginalObserver {
        constructor(callback, options) {
            super((entries, observer) => {
                const fakeEntries = entries.map(entry => {
                    return new Proxy(entry, {
                        get(target, prop) {
                            if (prop === 'isIntersecting') return true;
                            if (prop === 'intersectionRatio') return 1.0;
                            return Reflect.get(target, prop);
                        }
                    });
                });
                callback(fakeEntries, observer);
            }, options);
        }
    };
"""


def find_key_recursive(data, target_key):
    """Recursively search a JSON dictionary/list for a specific key."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == target_key and v is not None:
                yield v
            yield from find_key_recursive(v, target_key)
    elif isinstance(data, list):
        for item in data:
            yield from find_key_recursive(item, target_key)


def extract_review_data(next_data):
    """Extract review stats and latest review samples from __NEXT_DATA__."""
    queries = next_data.get("props", {}).get("dehydratedState", {}).get("queries", [])
    for query in queries:
        if not isinstance(query, dict):
            continue
        state = query.get("state") or {}
        state_data = state.get("data") or {}
        query_data = state_data.get("data") or {}
        modules = query_data.get("data_source_modules") or []

        for module in modules:
            if not isinstance(module, dict):
                continue
            module_data = module.get("module_data") or {}
            module_payload = module_data.get("data") or {}
            product = module_payload.get("product") or {}
            reviews = product.get("ratings_and_reviews")

            if not isinstance(reviews, dict):
                continue

            statistics = reviews.get("statistics") or {}
            rating = statistics.get("rating") or {}
            sample_reviews = []

            for review in reviews.get("most_recent") or []:
                if not isinstance(review, dict):
                    continue
                review_rating = review.get("rating") or {}
                author = review.get("author") or {}
                sample_reviews.append({
                    "author": author.get("nickname"),
                    "rating": review_rating.get("value"),
                    "title": review.get("title"),
                    "text": review.get("text"),
                    "submitted_at": review_rating.get("submitted_at"),
                })

            return {
                "rating": rating.get("average"),
                "rating_count": rating.get("count"),
                "review_count": statistics.get("review_count"),
                "sample_reviews": sample_reviews,
            }

    return {"rating": None, "rating_count": None, "review_count": None, "sample_reviews": []}


def save_batch_to_sqlite(db_conn, records):
    """Uses the existing project connection to push records using SQLite UPSERT."""
    if not records:
        return

    logger.info("Pushing batch of %d items to SQLite database...", len(records))

    sql = """
        INSERT INTO target_products (
            tcin, title, brand, price, formatted_price, 
            rating, review_count, primary_image, description, sample_reviews
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tcin) DO UPDATE SET
            title = excluded.title,
            brand = excluded.brand,
            price = excluded.price,
            formatted_price = excluded.formatted_price,
            rating = excluded.rating,
            review_count = excluded.review_count,
            primary_image = excluded.primary_image,
            description = excluded.description,
            sample_reviews = excluded.sample_reviews,
            updated_at = CURRENT_TIMESTAMP;
    """

    formatted_records = [
        (
            item["tcin"],
            item["title"],
            item["brand"],
            item["price"],
            item["formatted_price"],
            item["rating"],
            item["review_count"],
            item["primary_image"],
            item["description"],
            json.dumps(item["sample_reviews"])
        )
        for item in records
    ]

    try:
        cursor = db_conn.cursor()
        cursor.executemany(sql, formatted_records)
        db_conn.commit()
        logger.info("Batch commit successful (%d items).", len(records))
    except Exception as e:
        logger.error("SQLite batch execution failed: %s", e)
        db_conn.rollback()


def scrape_single_tcin(page, tcin):
    """Extracts raw data for a single TCIN using the active browser page."""
    target_url = f"https://www.target.com/p/-/-/A-{tcin}"
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_selector('[data-test="product-price"]', timeout=10000)
        except Exception:
            pass

        try:
            page.wait_for_selector('[data-test="rating-card-overall-rating"], [data-test="ratings-count"]', timeout=5000)
        except Exception:
            pass

        dom_data = page.evaluate("""() => {
            const getTxt = (sel) => {
                const el = document.querySelector(sel);
                return el ? el.textContent.trim() : null;
            };

            const imgEl = document.querySelector('img[data-test="@web/ProductImage/PrimaryImage"]') ||
                          document.querySelector('div[data-test="product-image"] img') ||
                          document.querySelector('picture img');

            return {
                formatted_price: getTxt('[data-test="product-price"]'),
                image_url: imgEl ? imgEl.src : null,
                rating_raw: getTxt('[data-test="rating-card-overall-rating"]') || getTxt('[data-test="ratings-count"]'),
                reviews_raw: getTxt('[data-test="review-count"]') || getTxt('[data-test="ratings-count"]')
            };
        }""")

        next_data = page.evaluate("() => window.__NEXT_DATA__ || {}")
        review_data = extract_review_data(next_data)

        title, description, brand = None, None, None

        for desc in find_key_recursive(next_data, "product_description"):
            if isinstance(desc, dict) and "title" in desc:
                title = desc.get("title")
                description = desc.get("downstream_description")
                break

        for b_item in find_key_recursive(next_data, "primary_brand"):
            if isinstance(b_item, dict) and "name" in b_item:
                brand = b_item.get("name")
                break

        rating_val = review_data["rating"]
        review_count_val = review_data["review_count"]

        if not rating_val:
            for stats in find_key_recursive(next_data, "ratings_and_reviews"):
                if isinstance(stats, dict):
                    rating_val = stats.get("average_rating") or stats.get("rating")
                    review_count_val = stats.get("total_reviews") or stats.get("count")
                    if rating_val:
                        break

        formatted_price = dom_data.get("formatted_price")
        price_num = float(re.search(r"[\d\.]+", formatted_price).group(0)) if formatted_price and re.search(r"[\d\.]+", formatted_price) else None

        return {
            "tcin": tcin,
            "title": title,
            "brand": brand,
            "price": price_num,
            "formatted_price": formatted_price,
            "rating": rating_val,
            "review_count": review_count_val,
            "primary_image": dom_data.get("image_url"),
            "description": description,
            "sample_reviews": review_data["sample_reviews"],
        }

    except Exception as e:
        logger.error("Failed to scrape TCIN %s: %s", tcin, e)
        return None


def run_target_scraper(tcin_list, db_conn):
    """
    Main entry point to import into your master project script.
    
    :param tcin_list: List of TCIN string IDs to scrape
    :param db_conn: Active sqlite3 connection object managed by your project architecture
    """
    playwright_cm = Stealth().use_sync(sync_playwright()) if STEALTH_AVAILABLE else sync_playwright()

    with playwright_cm as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        context.add_init_script(INTERSECTION_SCRIPT)

        page = context.new_page()
        buffer = []

        for index, tcin in enumerate(tcin_list, 1):
            logger.info("[%d/%d] Scraping TCIN: %s", index, len(tcin_list), tcin)
            
            data = scrape_single_tcin(page, tcin)
            if data:
                buffer.append(data)

            if len(buffer) >= BATCH_SIZE:
                save_batch_to_sqlite(db_conn, buffer)
                buffer.clear()

            time.sleep(REQUEST_DELAY)

        # Flush any remaining items in the buffer
        if buffer:
            save_batch_to_sqlite(db_conn, buffer)
            buffer.clear()

        browser.close()