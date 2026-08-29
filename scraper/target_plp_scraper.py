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


def extract_tcins_from_next_data(next_data: dict) -> Set[str]:
    """Extract all TCINs present in the __NEXT_DATA__ window state."""
    tcins = set()
    data_str = str(next_data)
    found = re.findall(r'"tcin"\s*:\s*"(\d+)"', data_str)
    tcins.update(found)
    return tcins


def scrape_category_tcins(category_url: str, max_scrolls: int = 3) -> List[str]:
    """Navigates to a Target category URL and extracts all visible TCINs."""
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

        try:
            logger.info("Opening Category URL: %s", category_url)
            page.goto(category_url, wait_until="domcontentloaded", timeout=30000)

            next_data = page.evaluate("() => window.__NEXT_DATA__ || {}")
            initial_tcins = extract_tcins_from_next_data(next_data)
            tcins.update(initial_tcins)
            logger.info("Found %d initial TCINs in page JSON", len(initial_tcins))

            for scroll in range(max_scrolls):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(1000)

            hrefs = page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a[href*="/p/"]'));
                return links.map(l => l.href);
            }""")

            for href in hrefs:
                match = re.search(r"A-(\d+)", href)
                if match:
                    tcins.add(match.group(1))

        except Exception as e:
            logger.error("Failed to extract TCINs from category page: %s", e)
        finally:
            browser.close()

    logger.info("Total unique TCINs extracted from category: %d", len(tcins))
    return list(tcins)