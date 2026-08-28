from datetime import date, timedelta
import time
import requests
from bs4 import BeautifulSoup

# Base URL pattern where {} will be replaced by the month/day string (e.g., '7/7_01.htm')
BASE_URL = "https://www.todayinsci.com/{}"


def generate_all_days():
    """Generates a list of tuples (month, day_str) for all 366 days of a leap year

    to ensure Feb 29th is included.
    """
    start_date = date(2024, 1, 1)  # 2024 is a leap year
    end_date = date(2024, 12, 31)
    delta = timedelta(days=1)

    day_list = []
    current_date = start_date
    while current_date <= end_date:
        month = current_date.month
        # Format day with leading zero if needed (e.g., '01')
        day_str = current_date.strftime("%d")
        day_list.append((month, day_str))
        current_date += delta

    return day_list


def scrape_names():
    days = generate_all_days()
    all_names = set()  # Using a set to automatically handle any duplicate entries

    print(f"Starting to scrape {len(days)} days...")

    for month, day_str in days:
        # Construct the URL suffix: e.g., '7/7_01.htm'
        url_suffix = f"{month}/{month}_{day_str}.htm"
        url = BASE_URL.format(url_suffix)

        try:
            # Adding a standard User-Agent header to mimic a regular browser request
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                # Use html.parser or lxml if installed
                soup = BeautifulSoup(response.content, "html.parser")

                # Find all <div class="daynameheading"> elements
                headings = soup.find_all("div", class_="daynameheading")

                for heading in headings:
                    # Extract the text inside the div, strip whitespace and the non-breaking spaces
                    text = heading.get_text(strip=True)
                    if text:
                        all_names.add(text)

                print(f"Successfully processed: {month}_{day_str}")
            else:
                print(
                    f"Failed to fetch {url_suffix} - Status Code: {response.status_code}"
                )

        except Exception as e:
            print(f"Error processing {url_suffix}: {e}")

        # Polite scraping practice: brief pause between requests to not overwhelm the server
        time.sleep(0.1)

    # Sort the names alphabetically and save to a text file
    sorted_names = sorted(list(all_names))
    output_file = "todayinsci_names.txt"

    with open(output_file, "w", encoding="utf-8") as f:
        for name in sorted_names:
            f.write(f"{name}\n")

    print(
        f"Finished! Extracted {len(sorted_names)} unique names and saved them to '{output_file}'."
    )


if __name__ == "__main__":
    scrape_names()
