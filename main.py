import os
import re
import time
import pandas as pd
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urlparse, urljoin

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager
from owner_researcher import research_and_verify_lead, clean_text, is_valid_phone

# =========================
# CONFIGURATION & CONSTANTS
# =========================

SEARCH_QUERIES_FILE = "search_queries.txt"
BACKUP_FILE = "live_backup.csv"
OUTPUT_FILE = "google_maps_leads_master.csv"

FINAL_COLUMNS = [
    "Owner Name",
    "Business Name",
    "Owner Phone Number",
    "Website URL",
    "Google Rating",
    "Review Count"
]

GOOGLE_MAPS_LOAD_WAIT = 4
LISTING_LOAD_WAIT = 2


# =========================
# SELENIUM DRIVER SETUP
# =========================

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--lang=en")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options,
    )
    return driver


def is_driver_alive(driver):
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False


def safe_quit_driver(driver):
    try:
        driver.quit()
    except Exception:
        pass


def read_search_queries():
    possible_files = [
        SEARCH_QUERIES_FILE,
        "search_queries",
        "queries.txt",
        "queries",
    ]

    file_path = None
    for file_name in possible_files:
        if os.path.exists(file_name):
            file_path = file_name
            break

    if not file_path:
        print("Search queries file not found. Create search_queries.txt.")
        return []

    queries = []
    with open(file_path, "r", encoding="utf-8") as file:
        for line in file:
            query = clean_text(line)
            if query and query not in queries:
                queries.append(query)

    return queries


def get_text_safe(driver, selectors):
    for selector in selectors:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
            text = clean_text(element.text)
            if text:
                return text
        except Exception:
            pass
    return ""


# =========================
# GOOGLE MAPS EXTRACTION
# =========================

def get_all_listing_links(driver):
    links = []
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/maps/place"]')
        for element in elements:
            href = element.get_attribute("href")
            if href and "/maps/place" in href and href not in links:
                links.append(href)
    except Exception:
        pass
    return links


def scroll_results(driver):
    try:
        feed = driver.find_element(By.CSS_SELECTOR, 'div[role="feed"]')
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", feed)
        time.sleep(2.5)
    except Exception as e:
        error_text = str(e).lower()
        if "invalid session id" in error_text or "session deleted" in error_text:
            raise
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.5)
        except Exception:
            pass


def extract_rating_and_reviews(driver):
    rating = ""
    review_count = ""

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        body_text = ""

    full_text = clean_text(body_text)

    rating_patterns = [
        r"([0-5]\.\d)\s+stars",
        r"([0-5]\.\d)\s+star",
        r"Rated\s+([0-5]\.\d)",
        r"rating\s+([0-5]\.\d)",
    ]

    review_patterns = [
        r"([\d,]+)\s+reviews",
        r"([\d,]+)\s+Google reviews",
        r"\(([\d,]+)\)",
    ]

    for pattern in rating_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE | re.MULTILINE)
        if match:
            rating = clean_text(match.group(1))
            break

    for pattern in review_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            review_count = clean_text(match.group(1)).replace(",", "")
            break

    return rating, review_count


def extract_gmaps_listing_raw(driver):
    wait = WebDriverWait(driver, 15)

    data = {
        "name": "",
        "address": "",
        "phone_number": "",
        "website_link": "",
        "google_rating": "",
        "review_count": "",
    }

    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))
    except Exception:
        pass

    time.sleep(LISTING_LOAD_WAIT)

    data["name"] = get_text_safe(driver, ["h1"])
    rating, review_count = extract_rating_and_reviews(driver)
    data["google_rating"] = rating
    data["review_count"] = review_count

    try:
        buttons_and_links = driver.find_elements(By.CSS_SELECTOR, "button, a")
    except Exception:
        buttons_and_links = []

    for item in buttons_and_links:
        try:
            aria = clean_text(item.get_attribute("aria-label") or "")
            href = clean_text(item.get_attribute("href") or "")

            if "Address:" in aria:
                data["address"] = clean_text(aria.replace("Address:", ""))

            if "Phone:" in aria:
                phone = clean_text(aria.replace("Phone:", ""))
                if is_valid_phone(phone):
                    data["phone_number"] = phone

            if href and href.startswith("http") and not data["website_link"]:
                domain = urlparse(href).netloc.lower()
                if (
                    "google.com" not in domain
                    and "gstatic.com" not in domain
                    and "ggpht.com" not in domain
                    and "googleusercontent.com" not in domain
                    and "maps.app.goo.gl" not in domain
                ):
                    data["website_link"] = href
        except Exception:
            pass

    return data


# =========================
# DEDUPLICATION & EXPORT
# =========================

def save_csv(scraped_data, output_file):
    df = pd.DataFrame(scraped_data)
    df = df.reindex(columns=FINAL_COLUMNS)

    if not df.empty:
        # Deduplicate on Business Name, Owner Phone Number, Website URL
        df = df.drop_duplicates(
            subset=["Business Name", "Owner Phone Number"],
            keep="first",
        )

    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    return len(df)


# =========================
# MAIN SCRAPER LOOP
# =========================

def scrape_query(
    driver,
    query,
    required_count,
    scraped_data,
    processed_links,
    seen_keys,
):
    print("\n====================================")
    print(f"Searching query: {query}")
    print("====================================")

    encoded_query = quote_plus(query)
    search_url = f"https://www.google.com/maps/search/{encoded_query}"

    driver.get(search_url)

    wait = WebDriverWait(driver, 40)
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div[role="feed"], a[href*="/maps/place"]')
            )
        )
        print("Google Maps search results loaded.")
    except Exception:
        print("Google Maps search page failed to load.")
        return False

    time.sleep(GOOGLE_MAPS_LOAD_WAIT)
    no_new_rounds = 0

    while len(scraped_data) < required_count:
        if not is_driver_alive(driver):
            print("Browser session lost.")
            return False

        listing_links = get_all_listing_links(driver)
        new_links = [link for link in listing_links if link not in processed_links]

        if not new_links:
            no_new_rounds += 1
            try:
                scroll_results(driver)
            except Exception:
                print("Browser session lost during scroll.")
                return False

            if no_new_rounds >= 6:
                print(f"No more new listings found for query: {query}")
                break
            continue

        no_new_rounds = 0

        for link in new_links:
            if len(scraped_data) >= required_count:
                break

            processed_links.add(link)

            try:
                driver.execute_script("window.open(arguments[0], '_blank');", link)
                driver.switch_to.window(driver.window_handles[-1])

                # 1. Step 1: Extract Google Maps listing info
                gmaps_data = extract_gmaps_listing_raw(driver)

                if not gmaps_data["name"]:
                    print("Skipped listing: Name not found.")
                else:
                    # 2. Step 2+: Deep Owner Research & Verification across public internet
                    verified_lead = research_and_verify_lead(gmaps_data)

                    if verified_lead:
                        dedup_key = f"{verified_lead['Business Name']}_{verified_lead['Owner Phone Number']}".lower()

                        if dedup_key in seen_keys:
                            print(f"Duplicate lead skipped: {verified_lead['Business Name']}")
                        else:
                            scraped_data.append(verified_lead)
                            seen_keys.add(dedup_key)

                            print(
                                f"\n[SUCCESS {len(scraped_data)}/{required_count}] Saved Lead:\n"
                                f"  Owner Name: {verified_lead['Owner Name']}\n"
                                f"  Business Name: {verified_lead['Business Name']}\n"
                                f"  Owner Phone Number: {verified_lead['Owner Phone Number']}\n"
                                f"  Website URL: {verified_lead['Website URL']}\n"
                                f"  Google Rating: {verified_lead['Google Rating']}\n"
                                f"  Review Count: {verified_lead['Review Count']}\n"
                            )

                            save_csv(scraped_data, BACKUP_FILE)

                try:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                except Exception:
                    pass

                time.sleep(1)

            except Exception as e:
                print("Error scraping listing:", e)
                try:
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                except Exception:
                    pass

        try:
            scroll_results(driver)
        except Exception:
            print("Browser session lost during scroll.")
            return False

    return True


def main():
    print("=========================================================")
    print(" Business Lead Research and Verification Engine v2.0")
    print(" Enforcing 20-Rule Verification, Phone Priority & Exact CSV")
    print("=========================================================\n")

    try:
        user_input = input("How many leads do you want? ")
        required_count = int(user_input)
    except Exception:
        print("Defaulting to 5 verified owner leads.")
        required_count = 5

    queries = read_search_queries()
    if not queries:
        return

    print(f"\nTotal search queries loaded: {len(queries)}")

    scraped_data = []
    processed_links = set()
    seen_keys = set()

    driver = setup_driver()

    try:
        query_index = 0
        while query_index < len(queries):
            if len(scraped_data) >= required_count:
                break

            query = queries[query_index]
            try:
                success = scrape_query(
                    driver=driver,
                    query=query,
                    required_count=required_count,
                    scraped_data=scraped_data,
                    processed_links=processed_links,
                    seen_keys=seen_keys,
                )

                if not success:
                    print("Restarting browser session and resuming...")
                    safe_quit_driver(driver)
                    driver = setup_driver()
                    time.sleep(3)
                else:
                    query_index += 1

            except Exception as e:
                print("Main scraping error:", e)
                safe_quit_driver(driver)
                driver = setup_driver()
                time.sleep(3)

        final_count = save_csv(scraped_data, OUTPUT_FILE)

        print("\n=========================================================")
        print(" SCRAPING COMPLETED")
        print(f" Target Leads Requested: {required_count}")
        print(f" Total Verified Leads Saved: {final_count}")
        print(f" Final Spreadsheet Saved: {OUTPUT_FILE}")
        print("=========================================================\n")

    finally:
        safe_quit_driver(driver)


if __name__ == "__main__":
    main()
