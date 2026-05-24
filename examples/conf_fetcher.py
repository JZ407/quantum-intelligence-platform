"""
Fetch and parse quantum conference list from quantum.info/conf/
"""
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime


def fetch_conferences(year: int = 2026):
    """Fetch all conferences from quantum.info/conf/ for a given year."""
    url = f"https://quantum.info/conf/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    conferences = []
    # The conference list is inside <div id="main"> -> <div class="inner"> -> <ul> or just <li>s
    # From curl output, each conference is a <li> with <b>date</b> and <a>name</a>
    for li in soup.find_all('li'):
        text = li.get_text(strip=True)
        if not text:
            continue
        # Pattern: <b>Month Day&ndash;Day:</b> <a href="...">Name</a> (Abbrev), Location.
        b_tag = li.find('b')
        a_tag = li.find('a', href=True)
        if not b_tag or not a_tag:
            continue

        date_str = b_tag.get_text(strip=True).rstrip(':').strip()
        name = a_tag.get_text(strip=True)
        href = a_tag.get('href', '')

        # Location is usually after the </a> tag, in the remaining text
        # Remove date and name from full text to get location
        remaining = text.replace(date_str, '').replace(name, '').strip()
        remaining = re.sub(r'^[:\s]+', '', remaining)
        # Remove common prefixes like "(Abbrev)," and trailing "."
        remaining = re.sub(r'^\([^)]*\)[,\s]*', '', remaining)
        remaining = remaining.rstrip('.').strip()
        location = remaining if remaining else 'TBA'

        # Parse date range
        month_map = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        # Date format examples: "Jan 5–9", "Jan 5&ndash;9", "Jan 12", "May 24&ndash;30"
        date_str_clean = date_str.lower().replace('&ndash;', '-').replace('–', '-')
        match = re.match(r'([a-z]{3})\s+(\d+)(?:-(\d+))?', date_str_clean)
        if not match:
            continue

        month_abbr = match.group(1)
        start_day = int(match.group(2))
        end_day = int(match.group(3)) if match.group(3) else start_day
        month = month_map.get(month_abbr, 0)
        if month == 0:
            continue

        start_date = datetime(year, month, start_day)
        end_date = datetime(year, month, end_day)

        conferences.append({
            'date_str': date_str,
            'start_date': start_date,
            'end_date': end_date,
            'month': month,
            'name_en': name,
            'location_en': location,
            'url': href,
        })

    return conferences


def filter_by_month(conferences: list, month: int):
    """Filter conferences for a specific month."""
    return [c for c in conferences if c['month'] == month]


if __name__ == '__main__':
    confs = fetch_conferences()
    print(f'Total conferences fetched: {len(confs)}')
    for c in confs[:5]:
        print(f"  {c['date_str']} | {c['name_en']} | {c['location_en']}")
