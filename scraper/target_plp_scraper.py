import json
import logging
import random
import time
from typing import List, Set
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""

def scrape_category_tcins(
    category_url: str, 
    target_count: int = 0, 
    store_id: str = "3263", 
    zip_code: str = "19107"
) -> List[str]:
    tcins: Set[str] = set()
    page_size = 24
    captured = {}

    # Seperate browser instances in plp and pdp scrapers because plp needs a headed
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )
        
        # Inject store location cookie directly into context before page load
        context.add_cookies([
            {
                "name": "guest_location",
                "value": f"{zip_code}%7C{store_id}%7C%7C%7C",
                "domain": ".target.com",
                "path": "/"
            }
        ])

        context.add_init_script(STEALTH_INIT_SCRIPT)
        page = context.new_page()

        def on_response(resp):
            if "plp_search_v2" in resp.url:
                logger.info("Saw plp_search_v2 -> status=%d", resp.status)
                if resp.status == 200 and not captured:
                    qs = parse_qs(urlparse(resp.url).query)
                    captured.update({k: v[0] for k, v in qs.items()})
                    logger.info("Captured params from a CONFIRMED 200 response")

        page.on("response", on_response)
        page.goto(category_url, wait_until="networkidle")
        page.wait_for_timeout(2000)

        if not captured:
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(2500)

        if not captured:
            raise RuntimeError(
                "Never observed a successful (200) plp_search_v2 request. "
                "The page's own requests are being blocked -- this is a "
                "session/fingerprint problem, not a replay problem."
            )

        offset = 0
        page_count = 0

        while target_count == 0 or len(tcins) < target_count:
            params = {
                **captured, 
                "pricing_store_id": str(store_id), 
                "zip": str(zip_code),
                "offset": str(offset), 
                "count": str(page_size)
            }
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2?{query}"

            # --- 1. RETRY WITH EXPONENTIAL BACKOFF FOR 502/503 ERRORS ---
            max_retries = 3
            result = None

            for attempt in range(1, max_retries + 1):
                result = page.evaluate(
                    """async (url) => {
                        const res = await fetch(url, { credentials: "include" });
                        return { status: res.status, body: await res.text() };
                    }""",
                    url,
                )

                if result["status"] == 200:
                    break  # Success!

                if result["status"] in (502, 503, 504):
                    backoff = attempt * 3.5  # 3.5s, 7.0s, 10.5s
                    logger.warning(
                        "Attempt %d/%d: Server error %d at offset=%d. Cooling down for %.1fs...",
                        attempt, max_retries, result["status"], offset, backoff
                    )
                    time.sleep(backoff)
                else:
                    break

            if result["status"] != 200:
                logger.error("Blocked or failed at offset=%d, status=%d", offset, result["status"])
                break

            payload = json.loads(result["body"])
            products = (payload.get("data") or {}).get("search", {}).get("products", [])
            if not products:
                logger.info("No more products found at offset %d. Reached end of category.", offset)
                break

            batch = {
                str(prod["tcin"])
                for prod in products
                if str(prod.get("tcin", "")).isdigit()
            }
            before = len(tcins)
            tcins.update(batch)
            logger.info("offset=%d: +%d new (total %d)", offset, len(tcins) - before, len(tcins))

            if len(tcins) == before:
                logger.info("No new unique TCINs discovered on pagination. Ending PLP harvest.")
                break

            offset += page_size
            page_count += 1

            # --- 2. PERIODIC BREATHER (Every 10 pages / ~240 items) ---
            if page_count % 10 == 0:
                breather_time = random.uniform(6.0, 10.0)
                logger.info("Fetched 10 pages. Taking a short breather for %.1fs...", breather_time)
                time.sleep(breather_time)
            else:
                # --- 3. DYNAMIC RANDOMIZED JITTER (1.8s to 3.6s) ---
                jitter = random.uniform(1.8, 3.6)
                time.sleep(jitter)
        browser.close()

    # return list(tcins)[:target_count]
    return list(tcins) if target_count == 0 else list(tcins)[:target_count] 


def extract_tcins_from_plp(data_obj) -> List[str]:
    products = (
        (data_obj.get("data") or {})
        .get("search", {})
        .get("products", [])
    )

    return [
        str(product["tcin"])
        for product in products
        if isinstance(product, dict)
        and str(product.get("tcin", "")).isdigit()
    ]