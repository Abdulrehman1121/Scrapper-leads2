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


# =========================
# SETTINGS
# =========================

SEARCH_QUERIES_FILE = "search_queries.txt"
BACKUP_FILE = "live_backup.csv"
OUTPUT_FILE = "google_maps_restaurant_leads.csv"

REQUIRE_PHONE_OR_EMAIL = False

GOOGLE_MAPS_LOAD_WAIT = 4
LISTING_LOAD_WAIT = 2
WEBSITE_PAGE_LIMIT = 8


# =========================
# REGEX / CONSTANTS
# =========================

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

PHONE_REGEX = (
    r"(\+1|1)?[\s\-.()]?\(?\d{3}\)?[\s\-.()]?\d{3}[\s\-.()]?\d{4}"
    r"|"
    r"(\+92|0092|92|0)?[\s-]?(3\d{2}|21|42|51)[\s-]?\d{3}[\s-]?\d{4}"
)

SOCIAL_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "pinterest.com",
]

BAD_EMAIL_PARTS = [
    "example.com",
    "domain.com",
    "email.com",
    "yourname",
    "name@",
    "test@",
    "sentry",
    "wixpress",
    "schema.org",
]

CONTACT_PAGE_KEYWORDS = [
    "contact",
    "about",
    "location",
    "locations",
    "visit",
    "reservation",
    "reservations",
    "booking",
    "book",
    "menu",
    "order",
    "catering",
    "support",
    "help",
]


# =========================
# BASIC HELPERS
# =========================

def clean_text(text):
    if not text:
        return ""
    return " ".join(str(text).split()).strip()


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
        print("Search queries file not found.")
        print("Create search_queries.txt in the same folder.")
        return []

    queries = []

    with open(file_path, "r", encoding="utf-8") as file:
        for line in file:
            query = clean_text(line)

            if query and query not in queries:
                queries.append(query)

    return queries


def request_html(url, timeout=12):
    if not url:
        return ""

    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )

        if response.status_code >= 400:
            return ""

        content_type = response.headers.get("Content-Type", "").lower()

        if content_type and "html" not in content_type:
            return ""

        return response.text

    except Exception:
        return ""


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
# GOOGLE MAPS HELPERS
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
        driver.execute_script(
            "arguments[0].scrollTop = arguments[0].scrollHeight",
            feed,
        )
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


def extract_phone_from_text(text):
    if not text:
        return ""

    match = re.search(PHONE_REGEX, text)

    if match:
        return clean_text(match.group())

    return ""


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


# =========================
# WEBSITE / EMAIL / SOCIAL SCRAPING
# =========================

def is_valid_business_email(email):
    if not email:
        return False

    email = email.strip().lower()

    if not re.match(EMAIL_REGEX, email):
        return False

    if any(bad in email for bad in BAD_EMAIL_PARTS):
        return False

    return True


def extract_emails_from_html(html):
    emails = set()

    if not html:
        return emails

    found_emails = re.findall(EMAIL_REGEX, html)

    for email in found_emails:
        email = email.strip()

        if is_valid_business_email(email):
            emails.add(email)

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        if href.lower().startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip()

            if is_valid_business_email(email):
                emails.add(email)

    return emails


def extract_socials_from_html(base_url, html):
    socials = set()

    if not html:
        return socials

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_href = urljoin(base_url, href)
        lower_href = full_href.lower()

        if any(domain in lower_href for domain in SOCIAL_DOMAINS):
            socials.add(full_href)

    return socials


def get_internal_contact_links(base_url, html):
    links = []

    if not base_url or not html:
        return links

    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower().replace("www.", "")

    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = clean_text(a.get_text(" ")).lower()
        full_url = urljoin(base_url, href)

        parsed = urlparse(full_url)
        domain = parsed.netloc.lower().replace("www.", "")

        if domain != base_domain:
            continue

        check_value = f"{full_url.lower()} {text}"

        if any(keyword in check_value for keyword in CONTACT_PAGE_KEYWORDS):
            if full_url not in links:
                links.append(full_url)

        if len(links) >= WEBSITE_PAGE_LIMIT:
            break

    return links


def extract_business_contact_from_website(website_url):
    result = {
        "email_id": "",
        "business_contact_page": "",
        "social_media_accounts": "",
    }

    if not website_url:
        return result

    homepage_html = request_html(website_url)

    if not homepage_html:
        return result

    emails = set()
    socials = set()

    emails.update(extract_emails_from_html(homepage_html))
    socials.update(extract_socials_from_html(website_url, homepage_html))

    internal_links = get_internal_contact_links(website_url, homepage_html)

    first_contact_page = ""

    for link in internal_links:
        html = request_html(link)

        if not html:
            continue

        if not first_contact_page:
            first_contact_page = link

        emails.update(extract_emails_from_html(html))
        socials.update(extract_socials_from_html(link, html))

        time.sleep(0.4)

    if emails:
        result["email_id"] = ", ".join(sorted(emails))

    if first_contact_page:
        result["business_contact_page"] = first_contact_page

    if socials:
        result["social_media_accounts"] = ", ".join(sorted(socials))

    return result


# =========================
# LISTING DATA
# =========================

def extract_listing_data(driver):
    wait = WebDriverWait(driver, 20)

    data = {
        "name": "",
        "contact": "",
        "address": "",
        "social_media_accounts": "",
        "website_available": "No",
        "website_link": "",
        "business_contact_page": "",
        "phone_number": "",
        "email_id": "",
        "google_rating": "",
        "review_count": "",
        "source_query": "",
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

    socials = set()

    for item in buttons_and_links:
        try:
            text = clean_text(item.text)
            aria = clean_text(item.get_attribute("aria-label") or "")
            href = clean_text(item.get_attribute("href") or "")
            combined = clean_text(f"{text} {aria} {href}")

            if "Address:" in aria:
                address = aria.replace("Address:", "")
                data["address"] = clean_text(address)

            if "Phone:" in aria:
                phone = aria.replace("Phone:", "")
                data["phone_number"] = clean_text(phone)
                data["contact"] = data["phone_number"]

            if not data["phone_number"]:
                phone = extract_phone_from_text(combined)

                if phone:
                    data["phone_number"] = phone
                    data["contact"] = phone

            if href and href.startswith("http"):
                domain = urlparse(href).netloc.lower()

                if any(social in domain for social in SOCIAL_DOMAINS):
                    socials.add(href)

                elif (
                    "google.com" not in domain
                    and "gstatic.com" not in domain
                    and "ggpht.com" not in domain
                    and "googleusercontent.com" not in domain
                    and "maps.app.goo.gl" not in domain
                ):
                    if not data["website_link"]:
                        data["website_available"] = "Yes"
                        data["website_link"] = href

        except Exception:
            pass

    if not data["address"]:
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text
            lines = page_text.split("\n")

            for line in lines:
                line = clean_text(line)

                if len(line) > 15:
                    address_words = [
                        "karachi",
                        "dha",
                        "clifton",
                        "bahadurabad",
                        "gulshan",
                        "nazimabad",
                        "saddar",
                        "tariq road",
                        "shahrah",
                        "korangi",
                        "malir",
                        "pechs",
                        "zamzama",
                        "boat basin",
                    ]

                    if any(word in line.lower() for word in address_words):
                        data["address"] = line
                        break

        except Exception:
            pass

    if data["website_link"]:
        website_data = extract_business_contact_from_website(data["website_link"])

        if website_data["email_id"]:
            data["email_id"] = website_data["email_id"]

        if website_data["business_contact_page"]:
            data["business_contact_page"] = website_data["business_contact_page"]

        if website_data["social_media_accounts"]:
            for link in website_data["social_media_accounts"].split(", "):
                if link:
                    socials.add(link)

    data["social_media_accounts"] = ", ".join(sorted(socials))

    return data


# =========================
# DEDUPLICATION / CSV
# =========================

def normalize_phone(phone):
    phone = clean_text(phone).lower()
    phone = re.sub(r"[^0-9+]", "", phone)
    return phone


def normalize_website(website):
    website = clean_text(website).lower()
    website = website.replace("https://", "")
    website = website.replace("http://", "")
    website = website.replace("www.", "")
    website = website.rstrip("/")
    return website


def normalize_name_address(name, address):
    value = f"{name} {address}".lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = clean_text(value)
    return value


def is_duplicate(item, seen_names_addresses, seen_phones, seen_websites):
    name = item.get("name", "")
    address = item.get("address", "")
    phone = normalize_phone(item.get("phone_number", ""))
    website = normalize_website(item.get("website_link", ""))
    name_address = normalize_name_address(name, address)

    if phone and phone in seen_phones:
        return True

    if website and website in seen_websites:
        return True

    if name_address and name_address in seen_names_addresses:
        return True

    return False


def mark_seen(item, seen_names_addresses, seen_phones, seen_websites):
    name = item.get("name", "")
    address = item.get("address", "")
    phone = normalize_phone(item.get("phone_number", ""))
    website = normalize_website(item.get("website_link", ""))
    name_address = normalize_name_address(name, address)

    if phone:
        seen_phones.add(phone)

    if website:
        seen_websites.add(website)

    if name_address:
        seen_names_addresses.add(name_address)


def save_csv(scraped_data, output_file):
    columns = [
        "name",
        "contact",
        "address",
        "social_media_accounts",
        "website_available",
        "website_link",
        "business_contact_page",
        "phone_number",
        "email_id",
        "google_rating",
        "review_count",
        "source_query",
    ]

    df = pd.DataFrame(scraped_data)
    df = df.reindex(columns=columns)

    if not df.empty:
        df = df.drop_duplicates(
            subset=["phone_number", "website_link", "name", "address"],
            keep="first",
        )

    df.to_csv(output_file, index=False, encoding="utf-8-sig")

    return len(df)


# =========================
# SCRAPER LOOP
# =========================

def scrape_query(
    driver,
    query,
    required_count,
    scraped_data,
    processed_links,
    seen_names_addresses,
    seen_phones,
    seen_websites,
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
        print("Google Maps results loaded.")

    except Exception:
        print("Google Maps results did not load.")
        print("Page title:", driver.title)
        print("Current URL:", driver.current_url)
        return False

    time.sleep(GOOGLE_MAPS_LOAD_WAIT)

    no_new_rounds = 0

    while len(scraped_data) < required_count:
        if not is_driver_alive(driver):
            print("Browser session lost.")
            return False

        listing_links = get_all_listing_links(driver)

        new_links = [
            link for link in listing_links
            if link not in processed_links
        ]

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

                item = extract_listing_data(driver)
                item["source_query"] = query

                has_contact = bool(item["phone_number"] or item["email_id"])

                if not item["name"]:
                    print("Skipped: no name found.")

                elif REQUIRE_PHONE_OR_EMAIL and not has_contact:
                    print(f"Skipped no phone/email: {item['name']}")

                elif is_duplicate(
                    item,
                    seen_names_addresses,
                    seen_phones,
                    seen_websites,
                ):
                    print(f"Duplicate skipped: {item['name']}")

                else:
                    scraped_data.append(item)
                    mark_seen(
                        item,
                        seen_names_addresses,
                        seen_phones,
                        seen_websites,
                    )

                    print(
                        f"[{len(scraped_data)}] Scraped: {item['name']} | "
                        f"Phone: {item['phone_number']} | "
                        f"Email: {item['email_id']} | "
                        f"Rating: {item['google_rating']} | "
                        f"Reviews: {item['review_count']}"
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

                error_text = str(e).lower()

                if "invalid session id" in error_text or "session deleted" in error_text:
                    return False

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
    try:
        required_count = int(input("How many leads do you want? "))
    except ValueError:
        print("Please enter a valid number.")
        return

    queries = read_search_queries()

    if not queries:
        return

    print(f"\nTotal search queries found: {len(queries)}")
    print("Bot will keep moving to next query until required leads are completed.")
    print("Owner scraping is disabled. Scraping business data only.\n")

    scraped_data = []
    processed_links = set()
    seen_names_addresses = set()
    seen_phones = set()
    seen_websites = set()

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
                    seen_names_addresses=seen_names_addresses,
                    seen_phones=seen_phones,
                    seen_websites=seen_websites,
                )

                if not success:
                    print("Restarting browser and continuing...")

                    safe_quit_driver(driver)
                    driver = setup_driver()
                    time.sleep(3)

                else:
                    query_index += 1

            except Exception as e:
                print("Main scraping error:", e)
                print("Restarting browser and continuing...")

                safe_quit_driver(driver)
                driver = setup_driver()
                time.sleep(3)

        final_count = save_csv(scraped_data, OUTPUT_FILE)

        print("\nScraping completed.")
        print(f"Required leads: {required_count}")
        print(f"Total leads saved: {final_count}")
        print(f"CSV file saved as: {OUTPUT_FILE}")

        if final_count < required_count:
            print("\nNote:")
            print("Bot searched all queries but could not reach the exact required count.")
            print("Add more search queries in search_queries.txt and run again.")

    finally:
        safe_quit_driver(driver)


if __name__ == "__main__":
    main()
