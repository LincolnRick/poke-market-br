# scrapers/cardmarket.py
"""
Scraper do Cardmarket (https://www.cardmarket.com)
- Busca pelo termo + "pokemon"
- Lê resultados e tenta extrair o "Average Sell Price" (EUR) ou preço listado
- Converte para BRL via env (FX_EUR_BRL) ou default 6.0
OBS.: Cardmarket tem variações de layout. Este parser é tolerante e usa seletores múltiplos.
"""

import os
import re
import time
import requests
from typing import List
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from .base import BaseScraper, PriceResult

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

def _fx_eur_brl() -> float:
    try:
        return float(os.getenv("FX_EUR_BRL", "6.0"))
    except Exception:
        return 6.0

def _eur_to_brl(eur: float) -> float:
    return round(float(eur) * _fx_eur_brl(), 2)

def _parse_eur(text: str) -> float | None:
    """
    Converte strings como '€12.34' ou '12,34 €' para float 12.34.
    """
    if not text:
        return None
    t = text.strip()
    # remove espaços finos e símbolos
    t = t.replace("\xa0", " ").replace("€", "").replace("EUR", "").strip()
    # troca vírgula por ponto se necessário
    t = t.replace(".", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d{2})?)", t)
    return float(m.group(1)) if m else None

def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip())[:512]

class CardMarketScraper(BaseScraper):
    source_name = "cardmarket"

    def _search_url(self, query: str) -> str:
        # Usa a busca geral de produtos. Filtros específicos podem ser adicionados depois.
        q = f"{query} pokemon"
        return f"https://www.cardmarket.com/en/Pokemon/Products/Search?searchString={quote_plus(q)}"

    def _extract_rows(self, soup: BeautifulSoup):
        """
        Tenta pegar linhas de resultados no grid/lista principal.
        """
        # Layout novo: cartões com classe .product
        rows = soup.select(".product")
        if rows:
            return rows
        # Layout alternativo: tabela
        rows = soup.select("table.table tbody tr")
        if rows:
            return rows
        # Fallback genérico
        return soup.select("[data-type='product']")

    def _row_to_result(self, row, original_query: str) -> PriceResult | None:
        # Link + título
        link = (
            row.select_one("a.product__name") or
            row.select_one("a.ellipsis") or
            row.select_one("a[href*='/Pokemon/Products/']")
        )
        if not link or not link.get("href"):
            return None

        title = _clean_title(link.get_text(" ", strip=True))
        url = link["href"]
        if url.startswith("/"):
            url = "https://www.cardmarket.com" + url
        url = url.split("?")[0][:1024]

        # Tentativas de pegar Average Sell Price (EUR)
        # Exemplos de seletores que já vimos em variações:
        price_nodes = [
            row.select_one(".price-container .font-weight-bold"),
            row.select_one(".product__footer .font-weight-bold"),
            row.select_one("td.text-right"),
            row.select_one(".price"),
        ]
        eur_value = None
        for node in price_nodes:
            if not node:
                continue
            eur_value = _parse_eur(node.get_text(" ", strip=True))
            if eur_value:
                break

        if eur_value is None:
            # Tenta na página do item (mais custoso, usar parcimoniosamente)
            try:
                r2 = requests.get(url, headers=HEADERS, timeout=25)
                if r2.ok:
                    s2 = BeautifulSoup(r2.text, "html.parser")
                    alt_nodes = [
                        s2.select_one("div:nth-of-type(1) .col-price .font-weight-bold"),
                        s2.select_one(".product-navigation .price"),
                        s2.select_one("dd:contains('Average Price') + dd"),
                        s2.find(string=re.compile("Average( |)Sell( |)Price", re.I)),
                    ]
                    for n in alt_nodes:
                        if not n:
                            continue
                        txt = n if isinstance(n, str) else n.get_text(" ", strip=True)
                        eur_value = _parse_eur(txt)
                        if eur_value:
                            break
            except Exception:
                pass

        if eur_value is None:
            return None

        brl = _eur_to_brl(eur_value)
        return PriceResult(
            query=original_query,
            source=self.source_name,
            title=title,
            url=url,
            price_min_brl=brl,
            price_max_brl=brl,
        )

    def search(self, query: str) -> List[PriceResult]:
        url = self._search_url(query)
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        rows = self._extract_rows(soup)
        results: List[PriceResult] = []
        for row in rows:
            res = self._row_to_result(row, query)
            if res:
                results.append(res)
            if len(results) >= 12:
                break

        return results
