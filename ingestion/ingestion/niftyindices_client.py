"""Nifty index rebalancing cadence, scraped from niftyindices.com's static
resources page — no bot protection, plain server-rendered HTML (confirmed
live: a bare GET with a realistic User-Agent returns real HTML across all 11
index-family tables on the page — broad market, sectoral/thematic, strategy,
group, debt/bond, G-Sec, T-Bill/CP/CD, ...). This is *cadence* only (e.g.
"Semi-annually - Last working day of March and September"), not the
per-cycle list of which stocks actually get added/removed — NSE Indices
doesn't publish that as a scrapeable feed (their reconstitution
announcements are ad hoc PDFs/press releases), so actual inclusion/exclusion
events stay deferred; see init.sql's Domain 7 section header. BSE/Sensex has
no equivalent free source — bseindia.com's corporate-calendar and API
endpoints are all dead or JS-only (see bse_client.py).

Domain 8 addition: sectoral/thematic index constituent CSVs from the same
domain (niftyindices.com/IndexConstituent/ind_<slug>.csv) — same
no-bot-protection trust tier as the rebalancing-schedule page above, used to
populate instruments.sector for IndustryClassificationJob. See
fetch_sector_constituents' docstring for a data-shape caveat verified while
building this: the CSV's own header calls the classification column
"Industry", but it's actually NSE's coarser Sector-tier label, not a
per-company fine-grained industry — confirmed live by observing Ashok
Leyland (a truck/commercial-vehicle maker) classified as "Capital Goods" in
ind_niftyautolist.csv, not something auto-specific. Mapped to
instruments.sector accordingly, not instruments.industry."""

import csv
import io

import requests
from bs4 import BeautifulSoup

from .config import config

_URL = "https://www.niftyindices.com/resources/index-rebalancing-schedule"
_CONSTITUENT_URL = "https://niftyindices.com/IndexConstituent/ind_{slug}.csv"

# Verified live (2026-07-14): each of these returns a real
# "Company Name,Industry,Symbol,Series,ISIN Code" CSV, not a soft-404 HTML
# shell — niftyindices.com returns HTTP 200 with a normal-looking HTML page
# for a *wrong* slug too, so status code alone can't tell them apart; every
# slug below was individually confirmed to start with the real CSV header.
# Several other plausible slugs (niftyprivatebanklist, niftyfinservicelist,
# niftypvtbanklist) were tried and confirmed to be exactly this soft-404
# shape — left out, not silently assumed broken.
SECTOR_INDEX_SLUGS = [
    "niftyautolist",
    "niftybanklist",
    "niftyfmcglist",
    "niftyitlist",
    "niftymetallist",
    "niftypharmalist",
    "niftyrealtylist",
    "niftyenergylist",
    "niftymedialist",
    "niftypsubanklist",
    "niftyfinancelist",
    "niftyhealthcarelist",
    "niftyconsumerdurableslist",
    "niftyoilgaslist",
    "niftycpselist",
    "niftyinfralist",
    "niftymnclist",
    "niftycommoditieslist",
]


class NiftyIndicesFetchError(Exception):
    """Non-2xx response from a niftyindices.com endpoint."""


def fetch_rebalancing_schedule() -> list[dict]:
    resp = requests.get(_URL, headers={"User-Agent": config.HTTP_USER_AGENT}, timeout=20)
    if resp.status_code != 200:
        raise NiftyIndicesFetchError(
            f"unexpected status {resp.status_code} from niftyindices rebalancing-schedule page"
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []
    seen = set()
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) != 3 or not cells[0].isdigit():
                continue  # header row or something malformed, not a data row
            _, index_name, frequency = cells
            if index_name in seen:
                continue  # the same index can legitimately appear in more than one table section
            seen.add(index_name)
            rows.append({"index_name": index_name, "rebalance_frequency": frequency})
    return rows


def fetch_sector_constituents(slug: str) -> list[dict]:
    """One sectoral/thematic index's constituent CSV -> [{symbol, sector}].
    `sector` is the CSV's "Industry" column verbatim (see module docstring
    for why that's actually sector-tier, not fine-grained industry).

    niftyindices.com returns HTTP 200 with an HTML "not found" shell for an
    invalid slug rather than a real 404 — so a caller must not trust status
    code alone; this raises NiftyIndicesFetchError if the response doesn't
    actually start with the expected CSV header, same spirit as treating a
    soft-404 as a real fetch failure elsewhere in this codebase."""
    url = _CONSTITUENT_URL.format(slug=slug)
    resp = requests.get(url, headers={"User-Agent": config.HTTP_USER_AGENT}, timeout=20)
    if resp.status_code != 200 or not resp.text.lstrip().startswith("Company Name,Industry,Symbol"):
        raise NiftyIndicesFetchError(f"{slug}: not a real constituent CSV (soft-404 or unexpected shape)")

    reader = csv.DictReader(io.StringIO(resp.text))
    return [
        {"symbol": row["Symbol"].strip(), "sector": row["Industry"].strip()}
        for row in reader
        if row.get("Symbol")
    ]
