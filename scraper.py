import time
import re
import json
from playwright.sync_api import sync_playwright


def scroll_results(page, scrolls=3, pause=2):
    """Scroll the results panel to load more listings."""
    panel = page.query_selector("div[role='feed'], div.m6QErb[aria-label]")
    if panel:
        for _ in range(scrolls):
            panel.evaluate("el => el.scrollTop = el.scrollHeight")
            time.sleep(pause)


def extract_listing_data(page, listing):
    """Click a listing and extract its detail data."""
    data = {}
    try:
        listing.click()
        page.wait_for_timeout(2500)

        # Name
        name_el = page.query_selector("h1.DUwDvf")
        data["name"] = name_el.inner_text().strip() if name_el else ""

        # Rating
        rating_el = page.query_selector("div.F7nice span[aria-hidden='true']")
        data["rating"] = rating_el.inner_text().strip() if rating_el else ""

        # Reviews count
        review_el = page.query_selector("div.F7nice span[aria-label*='review']")
        if review_el:
            text = review_el.get_attribute("aria-label") or ""
            nums = re.findall(r"[\d,]+", text)
            data["reviews"] = nums[0].replace(",", "") if nums else ""
        else:
            data["reviews"] = ""

        # Category
        cat_el = page.query_selector("button.DkEaL")
        data["category"] = cat_el.inner_text().strip() if cat_el else ""

        # Address
        addr_el = page.query_selector(
            "button[data-item-id='address'] div.Io6YTe, "
            "div[data-item-id*='address'] div.Io6YTe"
        )
        data["address"] = addr_el.inner_text().strip() if addr_el else ""

        # Phone
        phone_el = page.query_selector(
            "button[data-item-id*='phone'] div.Io6YTe, "
            "button[data-tooltip='Copy phone number'] div.Io6YTe"
        )
        data["phone"] = phone_el.inner_text().strip() if phone_el else ""

        # Website
        website_el = page.query_selector(
            "a[data-item-id='authority'] div.Io6YTe, "
            "a[data-item-id*='authority'] div.Io6YTe"
        )
        data["website"] = website_el.inner_text().strip() if website_el else ""

        # Full website URL
        website_link = page.query_selector("a[data-item-id='authority'], a[data-item-id*='authority']")
        data["website_url"] = website_link.get_attribute("href") if website_link else ""

        # Hours
        hours_el = page.query_selector(
            "div[aria-label*='hour'] span.ZDu9vd span:nth-child(2), "
            "button[data-item-id='oh'] div.Io6YTe"
        )
        data["hours"] = hours_el.inner_text().strip() if hours_el else ""

        # Google Maps URL
        data["maps_url"] = page.url

    except Exception as e:
        data["error"] = str(e)

    return data


def scrape_google_maps(keyword, max_results=20, scroll_count=3):
    """
    Search Google Maps for the keyword and scrape business listings.
    Returns a list of dicts with business data.
    """
    results = []
    seen_names = set()

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
            search_url = f"https://www.google.com/maps/search/{keyword.replace(' ', '+')}"
            page.goto(search_url, timeout=30000)
            page.wait_for_timeout(4000)

            # Wait for results panel
            try:
                page.wait_for_selector(
                    "div[role='feed'], div.m6QErb[aria-label]", timeout=10000
                )
            except Exception:
                browser.close()
                return results

            # Scroll to load more results
            scroll_results(page, scrolls=scroll_count)

            # Get all listing links
            listings = page.query_selector_all("a.hfpxzc")
            count = min(len(listings), max_results)

            for i in range(count):
                try:
                    # Re-find listings each iteration (DOM may change after click)
                    listings = page.query_selector_all("a.hfpxzc")
                    if i >= len(listings):
                        break

                    listing = listings[i]
                    aria_label = listing.get_attribute("aria-label") or ""

                    # Skip duplicates by name
                    if aria_label.lower() in seen_names:
                        continue
                    seen_names.add(aria_label.lower())

                    # Scroll element into view
                    listing.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)

                    data = extract_listing_data(page, listing)

                    if not data.get("name"):
                        data["name"] = aria_label

                    if data.get("name"):
                        results.append(data)

                    # Go back to results
                    page.go_back()
                    page.wait_for_timeout(2000)

                except Exception:
                    try:
                        page.go_back()
                        page.wait_for_timeout(2000)
                    except Exception:
                        pass
                    continue

        finally:
            browser.close()

    return results


if __name__ == "__main__":
    import sys
    keyword = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "restaurants in New York"
    print(f"Searching: {keyword}")
    data = scrape_google_maps(keyword, max_results=5)
    print(json.dumps(data, indent=2))
