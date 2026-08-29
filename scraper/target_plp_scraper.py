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
            page.goto(category_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

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
    
    
    
    
    """
    Navigates to Target to establish valid browser session/cookies,
    then executes RedSky API fetches in-browser to bypass 403 blocks.
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
            # 1. First visit page to get valid Akamai/PerimeterX session cookies
            logger.info("Initializing session at: %s", category_url)
            page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # 2. Query API directly inside the browser session where headers/cookies exist natively
            while len(tcins) < target_count:
                logger.info("Querying RedSky API via in-browser fetch (offset=%d)...", offset)

                api_script = f"""
                async () => {{
                    const url = "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2?category={category_id}&count={page_size}&default_purchasability_filter=false&include_sponsored=true&include_review_summarization=true&offset={offset}&page=%2Fc%2F{category_id}&platform=desktop&pricing_store_id=3991&spellcheck=true&visitor_id=01A03EAD3DB50200A4D486E1B365C817&zip=44570&key=9f36aeafbe60771e321a7cc95a78140772ab3e96&channel=WEB&include_dmc_dmr=false";
                    const res = await fetch(url);
                    if (!res.ok) return {{ status: res.status, data: null }};
                    const data = await res.json();
                    return {{ status: 200, data: data }};
                }}
                """
                
                result_obj = page.evaluate(api_script)
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
    
    
    
    
    """
    Directly queries Target's RedSky PLP API via Playwright's built-in HTTP client.
    Bypasses browser scrolling completely and handles offset pagination.
    """
    cat_match = re.search(r"N-([a-zA-Z0-9]+)", category_url)
    category_id = cat_match.group(1) if cat_match else "u7fty"

    tcins: Set[str] = set()
    offset = 0
    page_size = 24

    endpoint = "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2"
    
    custom_headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    with sync_playwright() as p:
        request_context = p.request.new_context()

        while len(tcins) < target_count:
            params = {
                "category": category_id,
                "count": str(page_size),
                "default_purchasability_filter": "false",
                "include_sponsored": "true",
                "include_review_summarization": "true",
                "offset": str(offset),
                "page": f"/c/{category_id}",
                "platform": "desktop",
                "pricing_store_id": "3991",
                "spellcheck": "true",
                "visitor_id": "01A03EAD3DB50200A4D486E1B365C817",
                "zip": "44570",
                "key": "9f36aeafbe60771e321a7cc95a78140772ab3e96",
                "channel": "WEB",
                "include_dmc_dmr": "false",
                "useragent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            }

            try:
                logger.info("Querying RedSky API (offset=%d, category=%s)...", offset, category_id)
                response = request_context.get(endpoint, params=params, headers=custom_headers, timeout=10000)

                if not response.ok:
                    logger.error("RedSky API request failed with HTTP status: %d", response.status)
                    break

                payload = response.json()
                products = (
                    payload.get("data", {})
                    .get("search", {})
                    .get("products", [])
                )

                if not products:
                    logger.warning("No products returned from API at offset %d.", offset)
                    break

                batch = [
                    str(product["tcin"])
                    for product in products
                    if isinstance(product, dict) and str(product.get("tcin", "")).isdigit()
                ]

                before_count = len(tcins)
                tcins.update(batch)
                added = len(tcins) - before_count

                logger.info("Retrieved %d products (%d new, total: %d)", len(batch), added, len(tcins))

                if added == 0:
                    logger.info("No new unique TCINs found. Stopping query.")
                    break

                offset += page_size

            except Exception as exc:
                logger.error("Error executing API request at offset %d: %s", offset, exc)
                break

        request_context.dispose()

    result = list(tcins)[:target_count]
    logger.info("Total TCINs harvested: %d", len(result))
    return result
    
    """
    Queries Target's RedSky API using Playwright's native API request client.
    No extra packages (like requests) needed.
    """
    cat_match = re.search(r"N-([a-zA-Z0-9]+)", category_url)
    category_id = cat_match.group(1) if cat_match else "u7fty"

    tcins: Set[str] = set()
    offset = 0
    page_size = 24

    endpoint = "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2"

    with sync_playwright() as p:
        # Use Playwright's built-in HTTP request context
        request_context = p.request.new_context(
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
                "Accept": "application/json",
            }
        )

        while len(tcins) < target_count:
            params = {
                "category": category_id,
                "count": str(page_size),
                "default_purchasability_filter": "false",
                "include_sponsored": "true",
                "include_review_summarization": "true",
                "offset": str(offset),
                "page": f"/c/{category_id}",
                "platform": "desktop",
                "pricing_store_id": "3991",
                "spellcheck": "true",
                "visitor_id": "01A03EAD3DB50200A4D486E1B365C817",
                "zip": "44570",
                "key": "9f36aeafbe60771e321a7cc95a78140772ab3e96",
                "channel": "WEB",
                "include_dmc_dmr": "false",
                "useragent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            }

            try:
                logger.info("Requesting RedSky API page offset=%d for category=%s", offset, category_id)
                response = request_context.get(endpoint, params=params, timeout=10000)
                
                if not response.ok:
                    logger.error("API call failed with status: %d", response.status)
                    break

                payload = response.json()
                products = (
                    payload.get("data", {})
                    .get("search", {})
                    .get("products", [])
                )

                if not products:
                    logger.warning("No products returned at offset %d.", offset)
                    break

                batch = [
                    str(product["tcin"])
                    for product in products
                    if isinstance(product, dict) and str(product.get("tcin", "")).isdigit()
                ]

                before = len(tcins)
                tcins.update(batch)
                new_added = len(tcins) - before

                logger.info("API returned %d items (%d new, total: %d)", len(batch), new_added, len(tcins))

                if new_added == 0:
                    break

                offset += page_size

            except Exception as exc:
                logger.error("API request failed at offset %d: %s", offset, exc)
                break

        request_context.dispose()

    result = list(tcins)[:target_count]
    logger.info("Total TCINs returned: %d", len(result))
    return result
    
    
    """
    Directly queries Target's RedSky PLP API using offset pagination.
    Bypasses headless Playwright scrolling completely.
    """
    # Extract category ID (e.g., 'u7fty' from '/c/produce-grocery/-/N-u7fty')
    cat_match = re.search(r"N-([a-zA-Z0-9]+)", category_url)
    category_id = cat_match.group(1) if cat_match else "u7fty"

    tcins: Set[str] = set()
    offset = 0
    page_size = 24

    endpoint = "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    session = requests.Session()

    while len(tcins) < target_count:
        params = {
            "category": category_id,
            "count": page_size,
            "default_purchasability_filter": "false",
            "include_sponsored": "true",
            "include_review_summarization": "true",
            "offset": offset,
            "page": f"/c/{category_id}",
            "platform": "desktop",
            "pricing_store_id": "3991",
            "spellcheck": "true",
            "visitor_id": "01A03EAD3DB50200A4D486E1B365C817",
            "zip": "44570",
            "key": "9f36aeafbe60771e321a7cc95a78140772ab3e96",
            "channel": "WEB",
            "include_dmc_dmr": "false",
            "useragent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        }

        try:
            logger.info("Requesting RedSky API page offset=%d for category=%s", offset, category_id)
            res = session.get(endpoint, params=params, headers=headers, timeout=10)
            res.raise_for_status()
            
            payload = res.json()
            products = (
                payload.get("data", {})
                .get("search", {})
                .get("products", [])
            )

            if not products:
                logger.warning("No products returned from API at offset %d.", offset)
                break

            batch = [
                str(p["tcin"])
                for p in products
                if isinstance(p, dict) and str(p.get("tcin", "")).isdigit()
            ]

            before = len(tcins)
            tcins.update(batch)
            new_added = len(tcins) - before

            logger.info("API returned %d items (%d new, total: %d)", len(batch), new_added, len(tcins))

            # Stop if no new items came back to prevent infinite loops
            if new_added == 0:
                break

            # Increment offset for next page
            offset += page_size

        except Exception as exc:
            logger.error("RedSky API request failed at offset %d: %s", offset, exc)
            break

    result = list(tcins)[:target_count]
    logger.info("Total TCINs returned: %d", len(result))
    return result 
    
    
    
    
    
    tcins: Set[str] = set()

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

        # Intercept RedSky background requests for pagination batches
        def handle_response(response):
            if "/redsky_aggregations/v1/web/plp_search_v2" not in response.url:
                return

            try:
                payload = response.json()
                batch = extract_tcins_from_plp(payload)

                before = len(tcins)
                tcins.update(batch)

                logger.info(
                    "Loaded PLP batch: %d TCINs, %d new",
                    len(batch),
                    len(tcins) - before,
                )
            except Exception as exc:
                logger.warning("Could not parse PLP response: %s", exc)

        # This must be outside handle_response()
        page.on("response", handle_response)

        try:
            logger.info("Opening Category URL: %s", category_url)
            page.goto(
                category_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            page.wait_for_timeout(3000)

            try:
                page.click("body", timeout=1000)
                page.keyboard.press("Escape")
            except Exception:
                pass

            def harvest_dom_links():
                hrefs = page.evaluate("""() => {
                    return Array.from(
                        document.querySelectorAll('a[href*="/p/"]')
                    ).map(link => link.href);
                }""")

                for href in hrefs:
                    match = re.search(r"A-(\d+)", href)
                    if match:
                        tcins.add(match.group(1))

            harvest_dom_links()
            logger.info("Found %d initial TCINs", len(tcins))

            attempts = 0

            while len(tcins) < target_count and attempts < max_scrolls:
                attempts += 1

                page.mouse.wheel(0, 700)
                page.wait_for_timeout(1800)

                harvest_dom_links()

                logger.info(
                    "Scroll %d: Collected %d TCINs so far",
                    attempts,
                    len(tcins),
                )

        except Exception as exc:
            logger.error(
                "Failed to extract TCINs from category page: %s",
                exc,
            )
        finally:
            browser.close()

    result = list(tcins)[:target_count]
    logger.info("Total TCINs returned: %d", len(result))
    return result