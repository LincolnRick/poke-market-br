# scrapers/mercadolivre.py
"""
Mercado Livre (Brasil) — API oficial de busca.
Doc base: https://api.mercadolibre.com/sites/MLB/search?q=<query>

Melhorias:
- Gera variantes de busca (Charizard 4/102 → "Charizard 4 102", "Charizard 4", "Charizard")
- Mantém apenas resultados em BRL.
- Dedup automático por permalink.
"""

from __future__ import annotations

import re
import time
from typing import List, Optional, Dict, Any, Iterable

import requests

from .base import BaseScraper, PriceResult

SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"

HEADERS = {
    "User-Agent": "poke-market-br/1.1 (+mvp)",
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def _safe_float(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if x > 0 else None
    except Exception:
        return None


def _variants(q: str) -> List[str]:
    """Gera até ~5 variações tolerantes para a busca."""
    s = (q or "").strip()
    if not s:
        return []

    vars_set = set()

    # original
    vars_set.add(s)

    # troca separadores por espaço: 4/102 -> 4 102
    s_sep = re.sub(r"[/\-_]+", " ", s)
    s_sep = re.sub(r"\s+", " ", s_sep).strip()
    if s_sep and s_sep != s:
        vars_set.add(s_sep)

    # se tiver padrão d+/d+, cria:
    m = re.search(r"(\d+)\s*[/\-]\s*(\d+)", s)
    if m:
        n1, n2 = m.group(1), m.group(2)
        # remove o "/total", fica só o primeiro número
        only_first = re.sub(r"(\d+)\s*[/\-]\s*(\d+)", n1, s)
        only_first = re.sub(r"\s+", " ", only_first).strip()
        if only_first:
            vars_set.add(only_first)

    # versão só com o nome (remove números/parenteses)
    name_only = re.sub(r"[\(\)\[\]#]", " ", s)
    name_only = re.sub(r"\d+(\s*[/\-]\s*\d+)?", " ", name_only)
    name_only = re.sub(r"\s+", " ", name_only).strip()
    if name_only and len(name_only) >= 3:
        vars_set.add(name_only)

    # mantém ordem estável: prioriza as mais específicas
    ordered = []
    for cand in (s, s_sep, only_first if m else None, name_only):
        if cand and cand in vars_set and cand not in ordered:
            ordered.append(cand)

    # fallback: quaisquer extras que tenham sobrado
    for cand in vars_set:
        if cand not in ordered:
            ordered.append(cand)

    # limita
    return ordered[:5]


def _search_once(q: str) -> List[Dict[str, Any]]:
    params = {
        "q": q,
        "limit": 50,
        "sort": "relevance",
    }
    try:
        r = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data.get("results") or []
    except Exception:
        return []


class MercadoLivreScraper(BaseScraper):
    source_name = "mercadolivre"

    def search(self, query: str) -> List[PriceResult]:
        q = (query or "").strip()
        if len(q) < 2:
            return []

        results: List[PriceResult] = []
        seen_urls = set()

        for qv in _variants(q):
            items = _search_once(qv)

            for it in items:
                title = (it.get("title") or "").strip()
                url = it.get("permalink") or ""
                currency = (it.get("currency_id") or "").upper()
                price = _safe_float(it.get("price"))

                if not title or not url or currency != "BRL" or price is None:
                    continue
                if url in seen_urls:
                    continue

                seen_urls.add(url)
                results.append(
                    PriceResult(
                        query=q,  # mantém o termo original
                        source=self.source_name,
                        title=title[:512],
                        url=url,
                        price_min_brl=round(price, 2),
                        price_max_brl=round(price, 2),
                    )
                )

            # se já colhemos bastante coisa, não precisa testar mais variações
            if len(results) >= 40:
                break

            # backoff leve entre variações
            time.sleep(0.25)

        # backoff final
        time.sleep(0.3)
        return results
