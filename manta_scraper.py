import re
import cloudscraper
from bs4 import BeautifulSoup


def scrape_manta(keyword, location="", max_pages=3):
    """
    Scrape Manta.com for business listings.
    Uses cloudscraper to bypass Cloudflare protection.
    Returns a list of dicts with business data.
    """
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    results = []
    seen_names = set()

    for page_num in range(1, max_pages + 1):
        params = {
            "search": keyword,
            "search_source": "nav",
            "device": "desktop",
            "screenResolution": "1920x1080",
            "page_size": "25",
        }

        if location:
            # Try to parse "City, State" format
            parts = [p.strip() for p in location.split(",")]
            if len(parts) >= 2:
                params["city"] = parts[0]
                params["state"] = parts[1]
                params["country"] = "United States"
            else:
                params["city"] = location
                params["country"] = "United States"

        if page_num > 1:
            params["page"] = str(page_num)

        try:
            response = scraper.get("https://www.manta.com/search", params=params, timeout=30)
            if response.status_code != 200:
                print(f"Manta page {page_num} returned status {response.status_code}")
                break

            soup = BeautifulSoup(response.text, "html.parser")

            # Find all listing cards - they contain business info
            # Each listing has: name (h2 a), address, phone, website link
            listings = soup.select(".list-items .hover\\:shadow-lg")
            if not listings:
                # Try alternative selectors
                listings = soup.select("[class*='list-items'] > div > div")
            if not listings:
                # Broader approach - find all elements with business names
                listings = soup.find_all("div", class_=re.compile(r"shadow|border.*rounded"))

            if not listings:
                # Parse from text content directly
                results.extend(_parse_from_text(soup, seen_names))
                break

            for listing in listings:
                data = _extract_listing(listing, seen_names)
                if data:
                    results.append(data)

            # Check if there's a next page
            next_link = soup.select_one("a[aria-label='Next']") or soup.find("a", string=re.compile(r"next|›|»", re.I))
            if not next_link:
                break

        except Exception as e:
            print(f"Error scraping Manta page {page_num}: {e}")
            break

    return results


def _extract_listing(listing, seen_names):
    """Extract data from a single Manta listing element."""
    data = {}

    # Name - usually in an h2 > a tag or strong tag
    name_el = listing.find("h2") or listing.find("a", class_=re.compile(r"company|name|title"))
    if name_el:
        name_link = name_el.find("a") if name_el.name == "h2" else name_el
        data["name"] = (name_link or name_el).get_text(strip=True)
        if name_link and name_link.get("href"):
            href = name_link["href"]
            if not href.startswith("http"):
                href = "https://www.manta.com" + href
            data["maps_url"] = href
    else:
        # Try finding any prominent link
        strong = listing.find("strong") or listing.find("b")
        if strong:
            data["name"] = strong.get_text(strip=True)

    if not data.get("name"):
        return None

    # Skip duplicates
    name_lower = data["name"].lower().strip()
    if name_lower in seen_names:
        return None
    seen_names.add(name_lower)

    # Address
    addr_parts = []
    addr_el = listing.find(string=re.compile(r"\d+.*(?:St|Ave|Rd|Dr|Blvd|Ln|Way|Ct|Hwy)", re.I))
    if addr_el:
        addr_parts.append(addr_el.strip())
        # Look for city/state after
        next_sib = addr_el.find_next(string=re.compile(r"[A-Z]{2}"))
        if next_sib:
            addr_parts.append(next_sib.strip())
    data["address"] = ", ".join(addr_parts) if addr_parts else ""

    # If no address found, try looking for location icon pattern
    if not data["address"]:
        location_spans = listing.find_all(string=re.compile(r"[A-Z][a-z]+,\s*[A-Z]{2}"))
        if location_spans:
            data["address"] = location_spans[0].strip()

    # Phone
    phone_el = listing.find(string=re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"))
    if phone_el:
        phone_match = re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", phone_el)
        data["phone"] = phone_match.group(0) if phone_match else ""
    else:
        data["phone"] = ""

    # Website
    website_link = listing.find("a", string=re.compile(r"visit\s*website", re.I))
    if website_link:
        data["website"] = website_link.get("href", "")
        data["website_url"] = data["website"]
    else:
        data["website"] = ""
        data["website_url"] = ""

    # Category
    cat_el = listing.find(string=re.compile(r"categorized under|categorized as", re.I))
    if cat_el:
        # Get the text after "Categorized under"
        cat_text = re.sub(r"categorized (?:under|as)\s*", "", cat_el.strip(), flags=re.I)
        data["category"] = cat_text
    else:
        data["category"] = ""

    # Rating
    rating_el = listing.find(class_=re.compile(r"star|rating"))
    if rating_el:
        rating_text = rating_el.get_text(strip=True)
        rating_match = re.search(r"[\d.]+", rating_text)
        data["rating"] = rating_match.group(0) if rating_match else ""
    else:
        data["rating"] = ""

    data["reviews"] = ""
    data["hours"] = ""
    data["source"] = "manta"

    return data


def _parse_from_text(soup, seen_names):
    """Fallback: parse business info from raw text content."""
    results = []
    text = soup.get_text()

    # Find business entries by phone number pattern
    phone_pattern = re.compile(r"\((\d{3})\)\s*(\d{3})-(\d{4})")
    for match in phone_pattern.finditer(text):
        phone = match.group(0)

        # Try to get surrounding context
        start = max(0, match.start() - 200)
        end = min(len(text), match.end() + 100)
        context = text[start:end]

        # Extract name (usually before the phone)
        lines = context[:match.start() - start].strip().split("\n")
        name = ""
        for line in reversed(lines):
            line = line.strip()
            if len(line) > 3 and not re.match(r"^[\d\s()+.-]+$", line):
                name = line
                break

        if not name or name.lower() in seen_names:
            continue

        seen_names.add(name.lower())
        results.append({
            "name": name,
            "phone": phone,
            "address": "",
            "website": "",
            "website_url": "",
            "category": "",
            "rating": "",
            "reviews": "",
            "hours": "",
            "maps_url": "",
            "source": "manta",
        })

    return results


if __name__ == "__main__":
    import json
    import sys

    keyword = sys.argv[1] if len(sys.argv) > 1 else "restaurants"
    location = sys.argv[2] if len(sys.argv) > 2 else "New York, NY"

    print(f"Searching Manta: {keyword} in {location}")
    data = scrape_manta(keyword, location, max_pages=1)
    print(f"Found {len(data)} results")
    print(json.dumps(data, indent=2))
