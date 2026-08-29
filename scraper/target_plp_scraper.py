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

def extract_tcins_from_json(data_obj) -> Set[str]:
    """Extract TCINs recursively or via string matching from any JSON dict."""
    tcins = set()
    data_str = str(data_obj)
    found = re.findall(r'"tcin"\s*:\s*"(\d+)"', data_str)
    tcins.update(found)
    return tcins

def scrape_category_tcins(category_url: str, target_count: int = 10) -> List[str]:
    """Navigates to a Target category URL and extracts at least target_count TCINs."""
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

        # Sniff network requests for RedSky product batches arriving dynamically
        def handle_response(response):
            if "redsky" in response.url or "graphql" in response.url:
                try:
                    json_body = response.json()
                    new_tcins = extract_tcins_from_json(json_body)
                    tcins.update(new_tcins)
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            logger.info("Opening Category URL: %s", category_url)
            page.goto(category_url, wait_until="networkidle", timeout=30000)

            # Extract static initial payload TCINs
            next_data = page.evaluate("() => window.__NEXT_DATA__ || {}")
            tcins.update(extract_tcins_from_json(next_data))
            logger.info("Found %d initial TCINs", len(tcins))

            # Scroll loop to force dynamic loading until target_count is reached
            scroll_attempts = 0
            max_attempts = 10

            while len(tcins) < target_count and scroll_attempts < max_attempts:
                scroll_attempts += 1
                
                # Scroll down in increments to trigger lazy loaders
                page.evaluate("window.scrollBy(0, 1200)")
                page.wait_for_timeout(1500)

                # Check DOM hrefs for /p/ links
                hrefs = page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/p/"]'));
                    return links.map(l => l.href);
                }""")

                for href in hrefs:
                    match = re.search(r"A-(\d+)", href)
                    if match:
                        tcins.add(match.group(1))

                logger.info("Scroll %d: Collected %d TCINs so far", scroll_attempts, len(tcins))

        except Exception as e:
            logger.error("Failed to extract TCINs from category page: %s", e)
        finally:
            browser.close()

    result = list(tcins)[:target_count]
    logger.info("Total TCINs returned: %d", len(result))
    return result