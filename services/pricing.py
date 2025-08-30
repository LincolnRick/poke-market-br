"""Utilities to gather card prices from multiple scrapers.

This module coordinates the scraper classes defined in :mod:`scrapers` and
computes simple statistics (min/avg/max/median) over the collected results.
The intent is to provide a single entry point for the Flask app and other
callers to obtain pricing information for a given search query.
"""

from __future__ import annotations

from statistics import mean, median
from typing import Dict, List, Sequence, Type

from scrapers.base import BaseScraper, PriceResult
from scrapers.mercadolivre import MercadoLivreScraper
from scrapers.cardmarket import CardMarketScraper
from scrapers.ebay import EbayScraper
from scrapers.ligapokemon import LigaPokemonScraper
from scrapers.shopee import ShopeeScraper
from scrapers.pricecharting import PriceChartingScraper


# ---------------------------------------------------------------------------
# Scraper coordination
# ---------------------------------------------------------------------------

_SCRAPER_CLASSES: Sequence[Type[BaseScraper]] = (
    MercadoLivreScraper,
    LigaPokemonScraper,
    CardMarketScraper,
    EbayScraper,
    ShopeeScraper,
    PriceChartingScraper,
)


def _instantiate_scrapers() -> List[BaseScraper]:
    """Instantiate all scraper classes, ignoring failures.

    Some scrapers may require API keys or other environment configuration; if
    instantiation fails for any reason we simply skip that scraper to keep the
    pricing pipeline running.
    """

    instances: List[BaseScraper] = []
    for cls in _SCRAPER_CLASSES:
        try:
            instances.append(cls())
        except Exception:
            # Silently drop scrapers that cannot be constructed.
            continue
    return instances


def scrape_all(query: str) -> List[PriceResult]:
    """Run all available scrapers for *query* and return merged results."""

    query = (query or "").strip()
    if not query:
        return []

    results: List[PriceResult] = []
    for scraper in _instantiate_scrapers():
        try:
            results.extend(scraper.search(query))
        except Exception:
            # Scrapers are best-effort; skip failures.
            continue
    return results


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_stats(results: Sequence[PriceResult]) -> Dict[str, float]:
    """Compute simple statistics from a sequence of :class:`PriceResult`.

    Each result contributes the midpoint between ``price_min_brl`` and
    ``price_max_brl`` to the aggregation.  The function returns a mapping with
    the keys ``min``, ``max``, ``avg`` and ``median`` (all floats rounded to
    two decimal places).  If *results* is empty the values will be zero.
    """

    if not results:
        return {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}

    mids = [(r.price_min_brl + r.price_max_brl) / 2 for r in results]
    min_v = min(r.price_min_brl for r in results)
    max_v = max(r.price_max_brl for r in results)
    return {
        "min": round(min_v, 2),
        "max": round(max_v, 2),
        "avg": round(mean(mids), 2),
        "median": round(median(mids), 2),
    }


def scrape_and_price(query: str) -> Dict[str, object]:
    """Convenience helper returning both results and statistics."""

    results = scrape_all(query)
    return {
        "query": query,
        "results": [r.model_dump() for r in results],
        "stats": compute_stats(results),
    }
