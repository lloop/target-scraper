import os
import re
import json
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright
from database.database import get_db_connection

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BATCH_SIZE = 50
REQUEST_DELAY = 0.5
NUM_WORKERS = 4  # Adjust number of parallel browser contexts based on CPU/RAM

INTERSECTION_SCRIPT = """
    // Native webdriver mask
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

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

    msg = f"[INFO] Pushing batch of {len(records)} items to SQLite database..."
    logger.info(msg)

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
        success_msg = f"[INFO] Batch commit successful ({len(records)} items)."
        logger.info(success_msg)
    except Exception as e:
        err_msg = f"[ERROR] SQLite batch execution failed: {e}"
        logger.error(err_msg)
        db_conn.rollback()


def scrape_single_tcin(page, tcin):
    """Extracts raw data for a single TCIN using the active browser page."""
    target_url = f"https://www.target.com/p/-/-/A-{tcin}"
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_selector('[data-test="product-price"]', timeout=5000)
        except Exception:
            pass

        try:
            page.wait_for_selector('[data-test="rating-card-overall-rating"], [data-test="ratings-count"]', timeout=3000)
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

        # --- VALIDATION GUARD ---
        if title is None and formatted_price is None and brand is None:
            warn_msg = f"[WARNING] TCIN {tcin} returned empty attributes (Unavailable Page). Excluding from DB batch."
            logger.warning(warn_msg)
            return None

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
        err_msg = f"[ERROR] Failed to scrape TCIN {tcin}: {e}"
        logger.error(err_msg)
        return None


def worker_task(tcin_chunk, result_queue, worker_id):
    """Isolated Playwright worker thread running its own browser context."""
    logger.info(f"Worker-{worker_id} started with {len(tcin_chunk)} TCINs.")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York"
        )
        context.add_init_script(INTERSECTION_SCRIPT)
        page = context.new_page()

        for index, tcin in enumerate(tcin_chunk, 1):
            status_msg = f"Worker-{worker_id} [{index}/{len(tcin_chunk)}] Processing TCIN: {tcin}"
            logger.info(status_msg)

            data = scrape_single_tcin(page, tcin)

            if data and (data.get("title") or data.get("formatted_price") or data.get("brand")):
                result_queue.put(data)
            else:
                skip_msg = f"Worker-{worker_id} [SKIP] TCIN {tcin} excluded from database insert buffer."
                logger.info(skip_msg)

            time.sleep(REQUEST_DELAY)

        browser.close()


def db_writer_task(result_queue, stop_event, *args, **kwargs):
    """
    Dedicated background thread that opens its own connection 
    to safely consume and write scraped batches to SQLite.
    
    *args captures any extra positional arguments passed by the execution context.
    """
    db_conn = get_db_connection()
    buffer = []

    try:
        while not stop_event.is_set() or not result_queue.empty():
            try:
                item = result_queue.get(timeout=0.5)
                buffer.append(item)
                result_queue.task_done()

                if len(buffer) >= BATCH_SIZE:
                    save_batch_to_sqlite(db_conn, buffer)
                    buffer.clear()
            except queue.Empty:
                continue

        if buffer:
            save_batch_to_sqlite(db_conn, buffer)
            buffer.clear()
    finally:
        db_conn.close()
        logger.info("Database writer connection closed.")        
        
def run_target_scraper(tcin_list, db_conn, num_workers=NUM_WORKERS):
    """Main entry point distributing TCIN queue across parallel Playwright workers."""
    if not tcin_list:
        logger.info("No TCINs provided to run_target_scraper.")
        return

    logger.info(f"Starting parallel PDP scraper with {num_workers} workers for {len(tcin_list)} items.")

    result_queue = queue.Queue()
    stop_event = threading.Event()

    # Split TCIN list into chunks for each worker
    chunks = [tcin_list[i::num_workers] for i in range(num_workers)]
    chunks = [c for c in chunks if c]  # Drop empty chunks if any

    # Start single-threaded DB writer listener
    writer_thread = threading.Thread(
        target=db_writer_task,
        args=(result_queue, stop_event)
    )
    writer_thread.start()

    # Launch Playwright browser threads
    with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
        futures = [
            executor.submit(worker_task, chunk, result_queue, i + 1)
            for i, chunk in enumerate(chunks)
        ]
        for future in futures:
            future.result()

    # Wait for DB queue to flush before finishing
    stop_event.set()
    writer_thread.join()
    logger.info("All parallel scraper tasks complete.")