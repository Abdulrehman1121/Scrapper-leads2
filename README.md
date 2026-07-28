# Google Map Scraper

A Python Selenium-based Google Maps scraper for collecting publicly available business lead data from Google Maps search results.

This tool reads multiple search queries from a `search_queries.txt` file, opens Google Maps results, visits each business listing in a new browser tab, extracts available business details, removes duplicates, and saves the final leads into a CSV file.

## Features

* Reads bulk search queries from `search_queries.txt`
* Searches Google Maps query by query
* Automatically moves to the next query when one search is exhausted
* Stops when the required number of leads is collected
* Opens each Google Maps listing in a new browser tab
* Scrapes business name
* Scrapes phone number/contact number
* Scrapes address
* Scrapes website link
* Checks whether a website is available
* Extracts public email addresses from business websites when available
* Extracts social media links when available
* Scrapes Google rating
* Scrapes review count
* Avoids duplicate records
* Saves live backup while scraping
* Exports final data into CSV format

## Data Fields

The final CSV includes the following columns:

```text
name
contact
address
social_media_accounts
website_available
website_link
phone_number
email_id
google_rating
review_count
source_query
```

## Project Files

```text
main.py
requirements.txt
search_queries.txt
.gitignore
README.md
```

## Requirements

Install the required Python packages:

```bash
pip install -r requirements.txt
```

## Required Packages

```text
selenium
pandas
requests
beautifulsoup4
webdriver-manager
```

## Search Queries

Add your search queries inside `search_queries.txt`, one query per line.

Example:

```text
Roofing Contractor Houston, TX
Roofing Company Houston, TX
Commercial Roofing Houston, TX
Roof Repair Houston, TX
Roofing Contractor Dallas, TX
Roofing Company Dallas, TX
Commercial Roofing Dallas, TX
Roof Repair Dallas, TX
```

The scraper will start from the first query, collect as many unique leads as possible, then continue with the next query until the required number of leads is reached.

## Usage

Run the scraper:

```bash
python main.py
```

The script will ask:

```text
How many leads do you want?
```

Example:

```text
How many leads do you want? 500
```

The scraper will then read queries from `search_queries.txt` and start collecting leads.

## Output Files

The script creates a live backup file while scraping:

```text
live_backup.csv
```

The final output file is:

```text
google_maps_leads_master.csv
```

## Example Output

```csv
name,contact,address,social_media_accounts,website_available,website_link,phone_number,email_id,google_rating,review_count,source_query
Example Roofing Company,+17135551234,"Houston, TX","https://facebook.com/example","Yes","https://example.com","+17135551234","info@example.com","4.8","120","Roofing Contractor Houston, TX"
```

## Duplicate Handling

The scraper checks duplicates using:

```text
phone_number
website_link
name + address
```

This helps reduce repeated leads across multiple Google Maps search queries.

## Notes

Google Maps may sometimes show a captcha, consent page, or sign-in page. If that happens, clear it manually in the browser and run the script again.

Email addresses are not always available on Google Maps. The script checks the business website and extracts public emails only when they are available.

If the scraper does not reach the exact number of leads requested, it means all provided queries were exhausted or Google Maps did not provide enough unique public listings. Add more queries to `search_queries.txt` and run the script again.

## Disclaimer

This tool is for educational and research purposes only. It should only be used to collect publicly available business information. Use the tool responsibly and make sure your usage follows the terms of service of the websites you access.
