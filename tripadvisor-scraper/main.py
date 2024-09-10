import asyncio
import json
import math
from typing import List, Optional, TypedDict
from urllib.parse import urljoin

import httpx
from loguru import logger as log
from parsel import Selector

# Assuming `client` is properly configured in snippet1 or wherever you're handling HTTP requests
from snippet1 import client

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
}

class Preview(TypedDict):
    url: str
    name: str
    numberOfReviews: str
    rating: str
    address: str

def parse_search_page(response: httpx.Response) -> List[Preview]:
    """Parse result previews from TripAdvisor restaurant search page"""
    log.info(f"Parsing search page: {response.url}")
    parsed = []
    selector = Selector(response.text)

    # Update the selector to target restaurant names and URLs
    for box in selector.css("div.listing"):  # Adjust based on your website's HTML structure
        title = box.css("a.property_title::text").get(default="").strip()  # Extract restaurant name
        url = box.css("a.property_title::attr(href)").get(default="")  # Extract restaurant URL

        parsed.append(
            {
                "url": urljoin(str(response.url), url),  # Turn URL into an absolute URL
                "name": title,
                "numberOfReviews": "",  # Placeholder for number of reviews
                "rating": "",  # Placeholder for rating
                "address": "",  # Placeholder for address
            }
        )
    return parsed

async def scrape_restaurant_details(restaurant_url: str) -> (str, str, str):
    """Scrape the number of reviews, rating, and address from a restaurant's individual page"""
    log.info(f"Scraping restaurant details from: {restaurant_url}")
    response = await client.get(restaurant_url, headers=headers)
    assert response.status_code == 200, "Failed to retrieve restaurant page"

    selector = Selector(response.text)

    # Adjust the selectors based on the individual restaurant page structure
    address = selector.css("span.address::text").get(default="").strip()  # Extract restaurant address
    number_of_reviews = selector.css("span.review_count::text").get(default="").strip()  # Extract number of reviews
    rating = selector.css("span.ui_bubble_rating::attr(class)").re_first(r'bubble_(\d+)')  # Extract rating from class

    return number_of_reviews, rating, address

async def scrape_search(url: str, max_pages: Optional[int] = None) -> List[Preview]:
    """Scrape search results for a specific restaurant URL"""
    log.info(f"Scraping first search results page: {url}")
    first_page = await client.get(url, headers=headers)
    assert first_page.status_code == 200, "Scraper is being blocked"

    # Parse first page to get restaurant names and URLs
    results = parse_search_page(first_page)
    if not results:
        log.error("Query found no results")
        return []

    # Extract pagination metadata
    page_size = len(results)
    total_results_text = first_page.selector.css("span.results_count::text").get(default="")  # Update if necessary
    total_results = int(total_results_text.split()[0].replace(",", "")) if total_results_text else 0
    next_page_url = first_page.selector.css('a[aria-label="Next page"]::attr(href)').get()  # Update if necessary
    next_page_url = urljoin(url, next_page_url) if next_page_url else None
    total_pages = int(math.ceil(total_results / page_size)) if total_results else 1

    # Limit the number of pages to scrape if max_pages is set
    if max_pages and total_pages > max_pages:
        log.debug(f"Only scraping {max_pages} max pages out of {total_pages} total")
        total_pages = max_pages

    log.info(f"Found {total_results=}, {page_size=}. Scraping {total_pages} pagination pages")

    # Collect remaining pages (concurrently)
    other_page_urls = [
        next_page_url.replace(f"oa{page_size}", f"oa{page_size * i}")  # Ensure this matches the pagination pattern
        for i in range(1, total_pages)
    ] if next_page_url else []

    # Concurrently fetch and parse additional pages
    to_scrape = [client.get(url, headers=headers) for url in other_page_urls]
    for response in asyncio.as_completed(to_scrape):
        results.extend(parse_search_page(await response))

    # Now scrape additional details (number of reviews, rating, and address) for each restaurant
    for result in results:
        number_of_reviews, rating, address = await scrape_restaurant_details(result['url'])
        result['numberOfReviews'] = number_of_reviews
        result['rating'] = rating
        result['address'] = address

    return results

async def main():
    # Use the specific URL for the restaurant search page (e.g., Paris restaurants)
    url = "https://www.tripadvisor.com/Restaurants-g187147-Paris_Ile_de_France.html"
    results = await scrape_search(url, max_pages=3)  # Set max_pages if you want to limit the number of pages to scrape
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
