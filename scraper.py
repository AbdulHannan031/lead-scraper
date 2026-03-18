import time
import re
import json
from playwright.sync_api import sync_playwright


def scroll_and_collect_urls(page, max_results=20, scroll_count=3, pause=1, on_progress=None):
    """Scroll the results panel and collect all listing URLs."""
    panel = page.query_selector("div[role='feed'], div.m6QErb[aria-label]")
    if not panel:
        return []

    collected_urls = []
    prev_count = 0
    no_new_count = 0

    # ~7 results per scroll, calculate how many scrolls we need
    max_scrolls = max((max_results // 7) + 3, scroll_count + 3)

    for i in range(max_scrolls):
        panel.evaluate("el => el.scrollTop = el.scrollHeight")
        time.sleep(pause)

        listings = page.query_selector_all("a.hfpxzc")
        urls = []
        seen = set()
        for link in listings:
            href = link.get_attribute("href") or ""
            label = (link.get_attribute("aria-label") or "").lower()
            if href and label and label not in seen:
                seen.add(label)
                urls.append({"url": href, "label": label})

        collected_urls = urls

        if on_progress:
            on_progress("status", {"message": f"Scrolling... found {len(collected_urls)} listings so far"})

        if len(collected_urls) >= max_results:
            break

        if len(collected_urls) == prev_count:
            no_new_count += 1
            if no_new_count >= 2:
                break
        else:
            no_new_count = 0
        prev_count = len(collected_urls)

        end_el = page.query_selector("span.HlvSq, p.fontBodyMedium > span > span")
        if end_el:
            text = end_el.inner_text().lower()
            if "end of results" in text or "you've reached" in text:
                break

    return collected_urls[:max_results]


def extract_detail_data(page):
    """Extract business data from a detail page."""
    data = {}

    name_el = page.query_selector("h1.DUwDvf")
    data["name"] = name_el.inner_text().strip() if name_el else ""

    rating_el = page.query_selector("div.F7nice span[aria-hidden='true']")
    data["rating"] = rating_el.inner_text().strip() if rating_el else ""

    review_el = page.query_selector("div.F7nice span[aria-label*='review']")
    if review_el:
        text = review_el.get_attribute("aria-label") or ""
        nums = re.findall(r"[\d,]+", text)
        data["reviews"] = nums[0].replace(",", "") if nums else ""
    else:
        data["reviews"] = ""

    cat_el = page.query_selector("button.DkEaL")
    data["category"] = cat_el.inner_text().strip() if cat_el else ""

    addr_el = page.query_selector(
        "button[data-item-id='address'] div.Io6YTe, "
        "div[data-item-id*='address'] div.Io6YTe"
    )
    data["address"] = addr_el.inner_text().strip() if addr_el else ""

    phone_el = page.query_selector(
        "button[data-item-id*='phone'] div.Io6YTe, "
        "button[data-tooltip='Copy phone number'] div.Io6YTe"
    )
    data["phone"] = phone_el.inner_text().strip() if phone_el else ""

    website_el = page.query_selector(
        "a[data-item-id='authority'] div.Io6YTe, "
        "a[data-item-id*='authority'] div.Io6YTe"
    )
    data["website"] = website_el.inner_text().strip() if website_el else ""

    website_link = page.query_selector("a[data-item-id='authority'], a[data-item-id*='authority']")
    data["website_url"] = website_link.get_attribute("href") if website_link else ""

    hours_el = page.query_selector(
        "div[aria-label*='hour'] span.ZDu9vd span:nth-child(2), "
        "button[data-item-id='oh'] div.Io6YTe"
    )
    data["hours"] = hours_el.inner_text().strip() if hours_el else ""

    data["maps_url"] = page.url

    return data


def scrape_google_maps(keyword, max_results=20, scroll_count=3, on_progress=None):
    """
    Search Google Maps and scrape business listings.
    Uses multiple pages (tabs) in round-robin for speed, but all in one thread.
    """
    results = []

    def emit(event, data):
        if on_progress:
            on_progress(event, data)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            emit("status", {"message": "Opening Google Maps..."})
            search_url = f"https://www.google.com/maps/search/{keyword.replace(' ', '+')}"
            page.goto(search_url, timeout=30000)
            page.wait_for_timeout(3000)

            try:
                page.wait_for_selector(
                    "div[role='feed'], div.m6QErb[aria-label]", timeout=10000
                )
            except Exception:
                browser.close()
                return results

            emit("status", {"message": "Scrolling to load listings..."})

            listing_urls = scroll_and_collect_urls(page, max_results, scroll_count, on_progress=on_progress)
            total = len(listing_urls)

            emit("scrolling", {"found": total})

            if total == 0:
                emit("done", {"total": 0})
                browser.close()
                return results

            # Close search page
            page.close()

            # Open multiple tabs for round-robin fast scraping (single thread, no crash)
            NUM_TABS = 3
            tabs = [context.new_page() for _ in range(NUM_TABS)]

            for i, item in enumerate(listing_urls):
                try:
                    tab = tabs[i % NUM_TABS]

                    emit("scraping", {"current": i + 1, "total": total, "name": item["label"].title()})

                    tab.goto(item["url"], timeout=15000)
                    try:
                        tab.wait_for_selector("h1.DUwDvf", timeout=4000)
                    except Exception:
                        pass

                    data = extract_detail_data(tab)

                    if not data.get("name"):
                        data["name"] = item["label"].title()

                    if data.get("name"):
                        results.append(data)

                except Exception:
                    continue

            for tab in tabs:
                try:
                    tab.close()
                except Exception:
                    pass

            emit("done", {"total": len(results)})

        finally:
            browser.close()

    return results


if __name__ == "__main__":
    import sys
    keyword = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "restaurants in New York"
    print(f"Searching: {keyword}")

    def on_progress(event, data):
        print(f"  [{event}] {data}")

    data = scrape_google_maps(keyword, max_results=10, on_progress=on_progress)
    print(f"\nFound: {len(data)} results")
    print(json.dumps(data, indent=2))
