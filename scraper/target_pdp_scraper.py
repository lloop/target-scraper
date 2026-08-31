import os
import re
import json
import logging
import time
import random
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BATCH_SIZE = 50
# REQUEST_DELAY = 0.5

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
            tcin, category, title, brand, price, formatted_price, in_stock,
            rating, review_count, primary_image, description, sample_reviews
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tcin) DO UPDATE SET
            category = excluded.category,
            title = excluded.title,
            brand = excluded.brand,
            price = excluded.price,
            formatted_price = excluded.formatted_price,
            in_stock = excluded.in_stock,
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
            item["category"],
            item["title"],
            item["brand"],
            item["price"],
            item["formatted_price"],
            item["in_stock"],
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

        # Wait for price element or alternative containers to hydrate
        try:
            page.wait_for_selector(
                '[data-test="product-price"], [data-test="@web/Price/PriceFull"], [data-test="product-price-container"]', 
                timeout=8000
            )
        except Exception:
            logger.debug("Price selector timeout for TCIN %s. Attempting fallback query...", tcin)

        dom_data = page.evaluate("""() => {
            const getTxt = (sel) => {
                const el = document.querySelector(sel);
                return el ? el.textContent.trim() : null;
            };

            // Enhanced price extraction supporting standard, sale, and clearance DOM nodes
            let priceText = getTxt('[data-test="product-price"]');
            if (!priceText) priceText = getTxt('[data-test="@web/Price/PriceFull"]');
            if (!priceText) priceText = getTxt('[data-test="product-price-container"]');
            if (!priceText) {
                const priceContainer = document.querySelector('div[data-test="price-container"]');
                if (priceContainer) priceText = priceContainer.textContent.trim();
            }

            const imgEl = document.querySelector('img[data-test="@web/ProductImage/PrimaryImage"]') ||
                        document.querySelector('div[data-test="product-image"] img') ||
                        document.querySelector('picture img');

            // Out-of-stock detection: explicit soldOut text node, or absence of a live add-to-cart button
            const soldOutEl = document.querySelector('[data-test="soldOutText"], [data-test="outOfStockMessage"]'); 
            const addToCartEl = document.querySelector('[data-test="shippingButton"], [data-test="orderPickupButton"], button[data-test="addToCartButton"]');
            const isSoldOut = !!soldOutEl || (priceText === null && !addToCartEl);

            return {
                formatted_price: priceText,
                image_url: imgEl ? imgEl.src : null,
                rating_raw: getTxt('[data-test="rating-card-overall-rating"]') || getTxt('[data-test="ratings-count"]'),
                reviews_raw: getTxt('[data-test="review-count"]') || getTxt('[data-test="ratings-count"]'),
                in_stock: !isSoldOut
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

        # Fallback to JSON payload price extraction if DOM extraction returns None
        if not formatted_price:
            for p_item in find_key_recursive(next_data, "price"):
                if isinstance(p_item, dict):
                    formatted_price = p_item.get("formatted_current_price") or p_item.get("formatted_price")
                    if formatted_price:
                        break

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
            "in_stock": dom_data.get("in_stock", True),
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


def run_target_scraper(tcin_list, category, db_conn, store_id="3263", zip_code="19146"):
    """Main entry point running sequential PDP extraction on a single Playwright instance."""
    if not tcin_list:
        logger.info("No TCINs provided to run_target_scraper.")
        return

    logger.info(f"Starting sequential PDP scraper for {len(tcin_list)} items (Store ID: {store_id}, Zip: {zip_code}).")

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
        
        # Inject guest_location cookie so prices and stock availability mirror target store
        context.add_cookies([{
            "name": "guest_location",
            "value": f"{zip_code}%7C{store_id}%7C%7C%7C",
            "domain": ".target.com",
            "path": "/"
        }])

        context.add_init_script(INTERSECTION_SCRIPT)

        page = context.new_page()
        buffer = []

        for index, tcin in enumerate(tcin_list, 1):
            status_msg = f"[{index}/{len(tcin_list)}] Processing TCIN: {tcin}"
            logger.info(status_msg)

            data = scrape_single_tcin(page, tcin)
            
            data["category"] = category

            if data and (data.get("title") or data.get("formatted_price") or data.get("brand")):
                buffer.append(data)
            else:
                skip_msg = f"[SKIP] TCIN {tcin} excluded from database insert buffer."
                logger.info(skip_msg)

            if len(buffer) >= BATCH_SIZE:
                save_batch_to_sqlite(db_conn, buffer)
                buffer.clear()

            time.sleep(random.uniform(2.5, 5.5))

        if buffer:
            save_batch_to_sqlite(db_conn, buffer)
            buffer.clear()

        browser.close()

    logger.info("Sequential scraper tasks complete.")
    
    
def filter_tcins_needing_update(db_conn, tcin_list, max_age_days=7):
    """
    Filters out TCINs that were updated within the last `max_age_days`.
    Scrapes missing items OR items with stale prices.
    """
    if not tcin_list:
        return []

    placeholders = ",".join(["?"] * len(tcin_list))
    
    # Query TCINs updated recently (using SQLite date functions)
    sql = f"""
        SELECT tcin 
        FROM target_products 
        WHERE tcin IN ({placeholders})
          AND updated_at >= datetime('now', '-{max_age_days} days')
    """
    
    cursor = db_conn.cursor()
    cursor.execute(sql, tcin_list)
    fresh_tcins = set(row[0] for row in cursor.fetchall())
    
    # Keep items that are completely new OR stale
    to_scrape = [tcin for tcin in tcin_list if tcin not in fresh_tcins]
    
    logger.info(
        f"[DEDUP] Input: {len(tcin_list)} | Fresh (<{max_age_days}d): {len(fresh_tcins)} | Need Scrape: {len(to_scrape)}"
    )
    return to_scrape