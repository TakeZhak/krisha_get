import argparse
import csv
import random
import re
import time
from dataclasses import dataclass, asdict
from typing import Callable, Iterable, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


DEFAULT_START_URL = "https://krisha.kz/prodazha/kvartiry/"
DEFAULT_OUTPUT = "krisha_listings.csv"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.5 Safari/605.1.15",
]


@dataclass
class Listing:
    url: str
    price: Optional[int]
    price_per_m2: Optional[int]
    address: str
    area_m2: Optional[float]
    author_name: str
    author_company: str


class KrishaScraper:
    def __init__(
        self,
        start_url: str,
        delay_min: float = 1.0,
        delay_max: float = 2.5,
        timeout: int = 20,
        retries: int = 3,
    ) -> None:
        self.start_url = start_url
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _sleep(self) -> None:
        if self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))

    @staticmethod
    def _emit(message: str, log_callback: Optional[Callable[[str], None]]) -> None:
        print(message)
        if log_callback:
            log_callback(message)

    def fetch(self, url: str) -> str:
        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                if response.status_code in (429, 503):
                    raise requests.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response.text
            except requests.RequestException as error:
                last_error = error
                if attempt < self.retries:
                    backoff = attempt * 2
                    time.sleep(backoff)
                else:
                    break
        raise RuntimeError(f"Failed to load {url}: {last_error}")

    @staticmethod
    def parse_listing_links(html: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        # Keep only links from search cards; generic /a/show/ picks up many unrelated blocks.
        for a_tag in soup.select(".a-card__header-left a.a-card__title[href*='/a/show/']"):
            href = a_tag.get("href")
            if href:
                links.add(urljoin(base_url, href))
        return sorted(links)

    @staticmethod
    def parse_next_page(html: str, base_url: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        next_link = soup.select_one("a[rel='next']")
        if next_link and next_link.get("href"):
            return urljoin(base_url, next_link["href"])
        return None

    @staticmethod
    def _get_start_page(url: str) -> int:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        raw_page = query.get("page", ["1"])[0]
        try:
            page = int(raw_page)
            return max(page, 1)
        except ValueError:
            return 1

    @staticmethod
    def _set_page(url: str, page: int) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["page"] = [str(page)]
        new_query = urlencode(query, doseq=True)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )

    @staticmethod
    def _extract_text_by_label(soup: BeautifulSoup, label: str) -> str:
        label_lower = label.lower()
        for row in soup.select("dl"):
            term = row.find("dt")
            value = row.find("dd")
            if term and value and label_lower in term.get_text(strip=True).lower():
                return value.get_text(" ", strip=True)

        # Fallback for pages where labels are plain text blocks.
        for node in soup.find_all(string=True):
            if node and label_lower == node.strip().lower():
                parent = node.parent
                if parent:
                    sibling = parent.find_next_sibling()
                    if sibling:
                        text = sibling.get_text(" ", strip=True)
                        if text:
                            return text
        return ""

    @staticmethod
    def _parse_price(raw: str) -> Optional[int]:
        # Commercial ads can contain two prices: "170 000 за месяц / 8 500 за м²".
        # We always keep the first (main) price.
        parts = re.findall(r"\d[\d\s.,]*", raw or "")
        if not parts:
            return None
        digits = re.sub(r"[^\d]", "", parts[0])
        return int(digits) if digits else None

    @staticmethod
    def _parse_price_per_m2(raw: str) -> Optional[int]:
        # Example: "170 000 за месяц / 8 500 за м²" -> 8500
        if not raw:
            return None
        match = re.search(r"(\d[\d\s.,]*)\s*〒?\s*за\s*м²", raw, flags=re.IGNORECASE)
        if not match:
            return None
        digits = re.sub(r"[^\d]", "", match.group(1))
        return int(digits) if digits else None

    @staticmethod
    def _parse_area(raw: str) -> Optional[float]:
        match = re.search(r"(\d+[.,]?\d*)", raw or "")
        if not match:
            return None
        return float(match.group(1).replace(",", "."))

    @staticmethod
    def _extract_area_from_title(title_text: str) -> Optional[float]:
        # Example: "3-комнатная квартира · 87 м² · 4/9 этаж, Шамши ..."
        match = re.search(r"(\d+[.,]?\d*)\s*м²", title_text or "", flags=re.IGNORECASE)
        if not match:
            return None
        return float(match.group(1).replace(",", "."))

    @staticmethod
    def _extract_address_from_title(title_text: str) -> str:
        # Example after comma: "Шамши Калдаяков 58 — М.Тынышбайулы"
        # For commercial cards title can be a list of business categories with "·".
        if "·" in title_text:
            return ""
        if "," in title_text:
            return title_text.split(",", 1)[1].strip()
        return ""

    @staticmethod
    def _extract_address_from_page_title(page_title: str) -> str:
        # Example:
        # "Аренда - №1000996676: Мкр Мамыр-1 — Жк Спутник, Алматы, ... — за 170000 — Крыша"
        if not page_title:
            return ""
        match = re.search(r":\s*(.*?)\s+—\s+за\s+\d", page_title, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _normalize_company(raw: str) -> str:
        value = (raw or "").strip()
        if not value:
            return ""
        # Reject values that look like timestamps/numeric garbage.
        if re.fullmatch(r"[\d:\-+T.Z\s]+", value):
            return "None"
        # Keep only real names that contain at least one letter.
        if not re.search(r"[A-Za-zА-Яа-яЁё]", value):
            return "None"
        return value

    def parse_listing_detail(self, url: str, html: str) -> Listing:
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text("\n", strip=True)
        page_title = soup.title.get_text(" ", strip=True) if soup.title else ""

        price_text = ""
        price_node = soup.select_one(".offer__price")
        if price_node:
            price_text = price_node.get_text(" ", strip=True)

        address = ""
        address_node = soup.select_one(".offer__location-title")
        if address_node:
            address = address_node.get_text(" ", strip=True)

        area_raw = self._extract_text_by_label(soup, "Площадь")
        title_text = ""
        title_node = soup.select_one("h1")
        if title_node:
            title_text = title_node.get_text(" ", strip=True)

        author_name = ""
        author_company = ""

        author_node = soup.select_one(".owners__name")
        if author_node:
            author_name = author_node.get_text(" ", strip=True)

        company_node = soup.select_one(".owners__company")
        if company_node:
            author_company = company_node.get_text(" ", strip=True)

        if not author_name:
            fallback_author = soup.find(attrs={"data-name": "owner-name"})
            if fallback_author:
                author_name = fallback_author.get_text(" ", strip=True)

        if not address and title_text:
            address = self._extract_address_from_title(title_text)
        if not address and page_title:
            address = self._extract_address_from_page_title(page_title)

        area_value = self._parse_area(area_raw)
        if area_value is None and title_text:
            area_value = self._extract_area_from_title(title_text)

        if not author_company:
            match = re.search(r"Работает в компании\s+([^\n]+)", page_text)
            if match:
                author_company = match.group(1).strip()
            elif "Крыша Агент" in page_text:
                author_company = "Крыша Агент"
            elif "Специалист" in page_text:
                author_company = "Специалист"

        return Listing(
            url=url,
            price=self._parse_price(price_text),
            price_per_m2=self._parse_price_per_m2(price_text),
            address=address,
            area_m2=area_value,
            author_name=author_name,
            author_company=self._normalize_company(author_company),
        )

    def iterate_listing_urls(
        self,
        pages_limit: int,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Iterable[str]:
        start_page = self._get_start_page(self.start_url)
        page_count = 0
        seen = set()

        while page_count < pages_limit:
            current_page = start_page + page_count
            current_url = self._set_page(self.start_url, current_page)
            page_count += 1
            self._emit(f"[INFO] Parsing list page {page_count}: {current_url}", log_callback)
            html = self.fetch(current_url)
            links = self.parse_listing_links(html, current_url)
            self._emit(f"[INFO] Found {len(links)} listing links", log_callback)

            if not links:
                self._emit("[INFO] No listing links found, stopping pagination.", log_callback)
                break

            for link in links:
                if link not in seen:
                    seen.add(link)
                    yield link

            self._sleep()

    def run(
        self,
        pages_limit: int,
        listings_limit: Optional[int],
        progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Listing]:
        results: List[Listing] = []

        for listing_url in self.iterate_listing_urls(
            pages_limit=pages_limit,
            log_callback=log_callback,
        ):
            if listings_limit is not None and len(results) >= listings_limit:
                break

            try:
                self._emit(f"[INFO] Parsing listing: {listing_url}", log_callback)
                detail_html = self.fetch(listing_url)
                listing = self.parse_listing_detail(listing_url, detail_html)
                results.append(listing)
                self._emit(f"[OK] Parsed listing #{len(results)}: {listing_url}", log_callback)
                if progress_callback:
                    progress_callback(len(results), listings_limit)
                self._sleep()
            except Exception as error:  # noqa: BLE001
                self._emit(f"[WARN] Skip {listing_url}: {error}", log_callback)

        return results


def save_to_csv(path: str, rows: List[Listing]) -> None:
    fieldnames = [
        "url",
        "price",
        "price_per_m2",
        "address",
        "area_m2",
        "author_name",
        "author_company",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as csv_file:
        # Excel in RU/KZ locale usually expects ';' as CSV delimiter.
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Krisha.kz MVP scraper (Requests + BeautifulSoup + CSV)."
    )
    parser.add_argument(
        "--start-url",
        default=DEFAULT_START_URL,
        help="Search page URL (with filters if needed).",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help="How many search pages to parse.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max number of listings to parse (0 means no limit).",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Path to output CSV file.",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=1.0,
        help="Min delay between requests (seconds).",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=2.5,
        help="Max delay between requests (seconds).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    listings_limit = None if args.limit == 0 else args.limit

    scraper = KrishaScraper(
        start_url=args.start_url,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
    )
    rows = scraper.run(pages_limit=args.pages, listings_limit=listings_limit)

    save_to_csv(args.output, rows)
    print(f"[DONE] Saved {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
