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
endpoints are all dead or JS-only (see bse_client.py)."""

import requests
from bs4 import BeautifulSoup

from .config import config

_URL = "https://www.niftyindices.com/resources/index-rebalancing-schedule"


class NiftyIndicesFetchError(Exception):
    """Non-2xx response from the niftyindices rebalancing-schedule page."""


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
