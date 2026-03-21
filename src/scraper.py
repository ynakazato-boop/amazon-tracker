"""
Amazon.co.jp keyword rank scraper using Playwright.

- Checks up to 3 pages (max 48 results/page on PC = max rank 144)
- Returns rank=None if not found within 3 pages
- Rate limiting: random 20-40s delay between requests
- Applies playwright-stealth to reduce bot detection
"""

import asyncio
import logging
import random
import urllib.parse
from dataclasses import dataclass

from playwright.async_api import async_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

RESULTS_PER_PAGE = 48  # Amazon PC: 48 results per page
MAX_PAGES = 3           # Check up to page 3 → max rank 144

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


@dataclass
class RankResult:
    asin: str
    keyword: str
    rank: int | None    # 1-144, or None if not found
    page: int | None    # 1-3, or None if not found


async def _random_delay(min_s: float = 20.0, max_s: float = 40.0):
    delay = random.uniform(min_s, max_s)
    logger.debug(f"Waiting {delay:.1f}s")
    await asyncio.sleep(delay)


async def _human_scroll(page: Page):
    """Simulate human-like scrolling."""
    for _ in range(random.randint(3, 6)):
        await page.mouse.wheel(0, random.randint(300, 600))
        await asyncio.sleep(random.uniform(0.3, 0.8))


async def _get_asins_on_page(page: Page) -> list[str]:
    """Extract organic ASIN list from a search result page (preserving order).
    Sponsored/ad results are excluded via data-component-type filter.
    """
    # Only organic results have data-component-type="s-search-result"
    elements = await page.query_selector_all('[data-component-type="s-search-result"][data-asin]')
    asins = []
    for el in elements:
        asin = await el.get_attribute("data-asin")
        if asin and len(asin) == 10 and asin not in asins:
            asins.append(asin)
    return asins


async def check_rank(
    context: BrowserContext,
    asin: str,
    keyword: str,
) -> RankResult:
    """
    Search keyword on amazon.co.jp and find the rank of the given ASIN.
    Checks pages 1-3 (max rank 144). Returns rank=None if not found.
    """
    encoded_kw = urllib.parse.quote(keyword)
    page = await context.new_page()

    try:
        for page_num in range(1, MAX_PAGES + 1):
            url = (
                f"https://www.amazon.co.jp/s?k={encoded_kw}&page={page_num}"
            )
            logger.info(f"[{asin}] '{keyword}' page {page_num}: {url}")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as e:
                logger.warning(f"Navigation error on page {page_num}: {e}")
                break

            await _human_scroll(page)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            asins = await _get_asins_on_page(page)
            logger.debug(f"Page {page_num}: found {len(asins)} ASINs")

            if asin in asins:
                position_on_page = asins.index(asin) + 1
                overall_rank = (page_num - 1) * RESULTS_PER_PAGE + position_on_page
                logger.info(f"Found {asin} at rank {overall_rank} (page {page_num}, pos {position_on_page})")
                return RankResult(asin=asin, keyword=keyword, rank=overall_rank, page=page_num)

            # If fewer results than expected, no point checking next page
            if len(asins) < RESULTS_PER_PAGE:
                logger.info(f"Page {page_num} has only {len(asins)} results; stopping.")
                break

            if page_num < MAX_PAGES:
                await _random_delay(20.0, 40.0)

        logger.info(f"{asin} not found in top {MAX_PAGES * RESULTS_PER_PAGE} results for '{keyword}'")
        return RankResult(asin=asin, keyword=keyword, rank=None, page=None)

    finally:
        await page.close()


async def run_checks(targets: list[dict]) -> list[RankResult]:
    """
    Run rank checks for a list of targets.
    Each target: {"asin": str, "keyword": str, "note": str}
    """
    results: list[RankResult] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        for i, target in enumerate(targets):
            asin = target["asin"]
            keyword = target["keyword"]

            # New context per target (fresh cookies/fingerprint)
            ua = random.choice(USER_AGENTS)
            context = await browser.new_context(
                user_agent=ua,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={
                    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )

            try:
                # Apply stealth if available
                try:
                    from playwright_stealth import stealth_async
                    page = await context.new_page()
                    await stealth_async(page)
                    await page.close()
                except ImportError:
                    pass

                result = await check_rank(context, asin, keyword)
                results.append(result)
            except Exception as e:
                logger.error(f"Error checking {asin} / '{keyword}': {e}")
                results.append(RankResult(asin=asin, keyword=keyword, rank=None, page=None))
            finally:
                await context.close()

            # Rate limit between targets (except after last one)
            if i < len(targets) - 1:
                await _random_delay(20.0, 40.0)

        await browser.close()

    return results


def run_checks_sync(targets: list[dict]) -> list[RankResult]:
    """Synchronous wrapper for run_checks."""
    return asyncio.run(run_checks(targets))
