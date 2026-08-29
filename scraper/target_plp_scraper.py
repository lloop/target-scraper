import logging
import re
from typing import List, Set
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

INTERSECTION_SCRIPT = """
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

def scrape_category_tcins(category_url: str, max_scrolls: int = 10, target_count: int = 10) -> List[str]:
    """
    Extracts live session configuration from Target's window context,
    then executes in-browser API queries with valid dynamic keys to bypass 403s.
    """
    cat_match = re.search(r"N-([a-zA-Z0-9]+)", category_url)
    category_id = cat_match.group(1) if cat_match else "u7fty"

    tcins: Set[str] = set()
    offset = 0
    page_size = 24

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
        page = context.new_page()

        try:
            logger.info("Initializing session at: %s", category_url)
            # Changed wait_until from "networkidle" to "domcontentloaded" to fix the 30s timeout
            page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 1. Harvest initial server render payload (__NEXT_DATA__)
            next_data = page.evaluate("() => window.__NEXT_DATA__ || {}")
            found_initial = re.findall(r'"tcin"\s*:\s*"(\d+)"', str(next_data))
            tcins.update(found_initial)
            logger.info("Extracted %d initial TCINs from window data", len(tcins))

            # 2. Grab current live API key dynamically from page state
            api_key = page.evaluate("""() => {
                return (window.__TGT_CONFIG__ && window.__TGT_CONFIG__.apiKey) || 
                       (window.__NEXT_DATA__ && window.__NEXT_DATA__.runtimeConfig && window.__NEXT_DATA__.runtimeConfig.apiKey) || 
                       "9f36ab4d01aab35e6f15e0fc9260b860";
            }""")

            # 3. Paginate API in-browser using live session credentials
            while len(tcins) < target_count:
                logger.info("Executing in-browser RedSky fetch (offset=%d)...", offset)

                result_obj = page.evaluate(f"""
                async () => {{
                    try {{
                        const url = "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2?category={category_id}&count={page_size}&default_purchasability_filter=false&include_sponsored=true&include_review_summarization=true&offset={offset}&page=%2Fc%2F{category_id}&platform=desktop&pricing_store_id=3991&spellcheck=true&key={api_key}&channel=WEB";
                        const res = await fetch(url, {{
                            headers: {{
                                'accept': 'application/json'
                            }}
                        }});
                        if (!res.ok) return {{ status: res.status, data: null }};
                        const data = await res.json();
                        return {{ status: 200, data: data }};
                    }} catch (e) {{
                        return {{ status: 500, error: e.toString() }};
                    }}
                }}
                """)

                status = result_obj.get("status")

                if status != 200:
                    logger.error("In-browser API fetch failed with status: %s", status)
                    break

                payload = result_obj.get("data") or {}
                products = (
                    payload.get("data", {})
                    .get("search", {})
                    .get("products", [])
                )

                if not products:
                    logger.warning("No products returned at offset %d", offset)
                    break

                batch = [
                    str(product["tcin"])
                    for product in products
                    if isinstance(product, dict) and str(product.get("tcin", "")).isdigit()
                ]

                before_count = len(tcins)
                tcins.update(batch)
                added = len(tcins) - before_count

                logger.info("Retrieved %d items (%d new, total: %d)", len(batch), added, len(tcins))

                if added == 0:
                    break

                offset += page_size

        except Exception as exc:
            logger.error("Failed executing in-browser API extraction: %s", exc)
        finally:
            browser.close()

    result = list(tcins)[:target_count]
    logger.info("Total TCINs harvested: %d", len(result))
    return result
  