import json
import logging
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
    target_count: int = 200, 
    store_id: str = "3263", 
    zip_code: str = "19146"
) -> List[str]:
    tcins: Set[str] = set()
    page_size = 24
    captured = {}

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
        while len(tcins) < target_count:
            # Overrides pricing_store_id dynamically with the passed store_id parameter
            params = {
                **captured, 
                "pricing_store_id": str(store_id), 
                "zip": str(zip_code),
                "offset": str(offset), 
                "count": str(page_size)
            }
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2?{query}"

            result = page.evaluate(
                """async (url) => {
                    const res = await fetch(url, { credentials: "include" });
                    return { status: res.status, body: await res.text() };
                }""",
                url,
            )

            if result["status"] != 200:
                logger.error("Blocked at offset=%d, status=%d", offset, result["status"])
                break

            payload = json.loads(result["body"])
            products = (payload.get("data") or {}).get("search", {}).get("products", [])
            if not products:
                logger.warning("No products at offset %d, stopping", offset)
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
                break

            offset += page_size
            page.wait_for_timeout(400)  # small jitter between calls

        browser.close()

    return list(tcins)[:target_count]


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