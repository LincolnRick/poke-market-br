# scrapers/shopee.py
import time
from typing import List, Optional
import requests
from .base import BaseScraper, PriceResult

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://shopee.com.br/search",
    "X-Requested-With": "XMLHttpRequest",
}

SEARCH_URL = "https://shopee.com.br/api/v4/search/search_items"


def _norm_price_shopee(v: Optional[float]) -> Optional[float]:
    """
    A API da Shopee pode retornar preço em várias escalas (ex.: *100, *1000, *100000).
    Traz para BRL aproximado.
    """
    if v is None:
        return None
    x = float(v)

    # Tenta fatores comuns primeiro
    for factor in (100000, 1000, 100, 10):
        if x >= 1000 and (x / factor) < 200_000:
            return x / factor

    # Se já parece estar OK
    if x < 200_000:
        return x

    # Fallback defensivo
    while x > 200_000:
        x /= 10.0
    return x


class ShopeeScraper(BaseScraper):
    source_name = "shopee"

    def search(self, query: str) -> List[PriceResult]:
        params = {
            "by": "relevancy",
            "keyword": query,
            "limit": 20,
            "newest": 0,
            "order": "desc",
            "page_type": "search",
            "scenario": "PAGE_GLOBAL_SEARCH",
            "version": 2,
        }

        try:
            r = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return []

        results: List[PriceResult] = []
        for it in data.get("items", [])[:20]:
            model = it.get("item_basic") or it

            title = (model.get("name") or "").strip()
            if not title:
                continue

            # Coleta candidatos de preço em escalas diferentes
            cands = [
                _norm_price_shopee(model.get("price_min")),
                _norm_price_shopee(model.get("price_max")),
                _norm_price_shopee(model.get("price")),
                _norm_price_shopee(model.get("price_min_before_discount")),
                _norm_price_shopee(model.get("price_max_before_discount")),
            ]
            cands = [c for c in cands if c is not None]
            if not cands:
                continue

            pmin, pmax = min(cands), max(cands)

            # Sanity check e clamp
            if pmin > pmax:
                pmin, pmax = pmax, pmin
            if pmin <= 0:
                continue

            itemid = model.get("itemid") or it.get("itemid")
            shopid = model.get("shopid") or it.get("shopid")
            if not (itemid and shopid):
                continue

            url_item = f"https://shopee.com.br/product/{shopid}/{itemid}"

            results.append(
                PriceResult(
                    query=query,
                    source=self.source_name,
                    title=title[:512],
                    url=url_item,
                    price_min_brl=round(float(pmin), 2),
                    price_max_brl=round(float(pmax), 2),
                ).clamp()
            )

        # Evita rate limit agressivo
        time.sleep(1.2)
        return results
