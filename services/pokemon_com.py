"""Wrapper for Pokémon.com TCG JSON endpoints.

This module provides thin convenience helpers around the public
``pokemon.com`` endpoints used by the official site.  The endpoints
exposed by the website return JSON lists of sets and cards.  Example
URLs:

* https://www.pokemon.com/br/api/pokemon-tcg/sets
* https://www.pokemon.com/br/api/pokemon-tcg/cards?setCode=sv6&page=1&pageSize=250

The functions defined here purposely keep a very small surface area so
that they can easily be mocked or replaced in unit tests.
"""
from __future__ import annotations

from typing import Any, Dict, List

import requests

_BASE = "https://www.pokemon.com"
_SETS_PATH = "/api/pokemon-tcg/sets"
_CARDS_PATH = "/api/pokemon-tcg/cards"


def _build_url(path: str, locale: str) -> str:
    """Return a fully qualified URL for the given ``path`` and ``locale``.

    Parameters
    ----------
    path:
        Path starting with ``/api``.
    locale:
        Regional prefix such as ``"br"`` or ``"us"``.
    """
    locale = locale.strip().strip("/") or "us"
    return f"{_BASE}/{locale}{path}"


def fetch_sets(locale: str = "br", timeout: int = 15) -> List[Dict[str, Any]]:
    """Fetch the list of TCG sets available on Pokémon.com.

    The function returns an empty list when the network request fails or
    the response cannot be parsed as JSON.  Consumers should handle the
    possibility of missing data.
    """
    url = _build_url(_SETS_PATH, locale)
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    if isinstance(data, dict):  # endpoint might wrap results under a key
        # some variants use ``results`` or ``sets`` as the list field
        return list(data.get("results") or data.get("sets") or [])
    if isinstance(data, list):
        return data
    return []


def fetch_cards(
    set_code: str,
    *,
    locale: str = "br",
    page: int = 1,
    page_size: int = 250,
    timeout: int = 15,
) -> Dict[str, Any]:
    """Fetch card information for ``set_code`` from Pokémon.com.

    Parameters
    ----------
    set_code:
        Abbreviation used by the Pokémon site (e.g. ``"sv6"``).
    locale:
        Regional prefix such as ``"br"`` or ``"us"``.
    page:
        Page number starting at 1.
    page_size:
        Amount of records per page.  The official API accepts values up to
        250 which minimizes the number of network calls.

    Returns
    -------
    dict
        JSON dictionary representing the response.  An empty dict is
        returned when a request fails.
    """
    url = _build_url(_CARDS_PATH, locale)
    params = {"setCode": set_code, "page": page, "pageSize": page_size}
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception:
        return {}
