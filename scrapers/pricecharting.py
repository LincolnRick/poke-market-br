# scrapers/pricecharting.py
"""
Scraper do PriceCharting (https://www.pricecharting.com)
- Busca por termo + "pokemon tcg"
- Lê a tabela de resultados e captura o "Loose Price" (USD)
- Entra na página do item para pegar: set, número, raridade, preços por condição,
  tendência, imagem e data de lançamento.
- Converte USD para BRL via FX_USD_BRL (default 5.2)
"""

from __future__ import annotations

import os
import re
import time
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, PriceResult

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

def _fx_usd_brl() -> float:
    try:
        return float(os.getenv("FX_USD_BRL", "5.2"))
    except Exception:
        return 5.2

def _usd_to_brl(usd: Optional[float]) -> Optional[float]:
    if usd is None:
        return None
    return round(float(usd) * _fx_usd_brl(), 2)

def _parse_money_usd(text: str) -> Optional[float]:
    if not text:
        return None
    t = text.replace(",", "")
    m = re.search(r"\$([\d.]+)", t)
    return float(m.group(1)) if m else None

def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if txt:
                return txt
    return ""

def _meta_content(soup: BeautifulSoup, prop: str) -> str:
    el = soup.select_one(f'meta[property="{prop}"]') or soup.select_one(f'meta[name="{prop}"]')
    return (el.get("content") or "").strip() if el else ""

def _find_attr_value(soup: BeautifulSoup, label_variants: list[str]) -> str:
    """
    Busca em tabelas/deflists do PriceCharting pares 'Label' -> 'Value'.
    Tenta achar qualquer variação de rótulo (case-insensitive).
    """
    text = soup.get_text("\n", strip=True)
    # Tenta padrão simples "Rarity: Ultra Rare"
    for label in label_variants:
        m = re.search(label + r"\s*:\s*([^\n]+)", text, flags=re.I)
        if m:
            return m.group(1).strip()

    # Busca em tabelas (th/td) ou dt/dd
    for label in label_variants:
        # th -> td
        th = soup.find(lambda tag: tag.name in ("th", "dt") and tag.get_text(strip=True).lower() == label.lower())
        if th:
            sib = th.find_next("td") or th.find_next("dd")
            if sib:
                return sib.get_text(" ", strip=True)
    return ""

def _from_url_parts(item_url: str, part_index: int) -> str:
    try:
        parts = [p for p in item_url.split("/") if p]
        return parts[part_index]
    except Exception:
        return ""

def _guess_set_from_url(item_url: str) -> str:
    # .../game/pokemon-evolving-skies/dragonite-v-192 -> "pokemon-evolving-skies"
    try:
        parts = [p for p in item_url.split("/") if p]
        game_idx = parts.index("game")
        raw = parts[game_idx + 1]
        return raw.replace("-", " ").title()
    except Exception:
        return ""

def _guess_number_from_url(item_url: str) -> str:
    # ...-192 -> 192
    m = re.search(r"-([0-9]{1,4})/?$", item_url)
    return m.group(1) if m else ""

def _parse_trend_percent(soup: BeautifulSoup) -> Optional[float]:
    # procura coisas tipo +3% ou -2% perto dos preços
    text = soup.get_text(" ", strip=True)
    m = re.search(r"([+-]\s?\d{1,3}(?:\.\d+)?)\s*%", text)
    if m:
        try:
            return float(m.group(1).replace(" ", ""))
        except Exception:
            return None
    return None

class PriceChartingScraper(BaseScraper):
    source_name = "pricecharting"

    def _search_url(self, query: str) -> str:
        from requests.utils import quote
        q = f"{query} pokemon tcg"
        return f"https://www.pricecharting.com/search-products?q={quote(q)}&type=prices"

    def _fetch(self, url: str) -> BeautifulSoup:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")

    def _parse_item_detail(self, item_url: str) -> dict:
        soup = self._fetch(item_url)

        # título real da carta
        title = (
            _first_text(soup, ["h1.page-title", "h1", "title"]).strip()
            or _meta_content(soup, "og:title")
        )

        # campos textuais
        set_name = _find_attr_value(soup, ["Set", "Set Name"]) or _guess_set_from_url(item_url)
        card_number = _find_attr_value(soup, ["Card Number", "Number"]) or _guess_number_from_url(item_url)
        rarity = _find_attr_value(soup, ["Rarity"])

        # imagem e data
        image_url = _meta_content(soup, "og:image")
        release_date = _find_attr_value(soup, ["Release Date", "Released"])

        # preços por condição na página do item (Loose / Graded / New)
        def pick_price_by_label(labels: list[str]) -> Optional[float]:
            # tenta por rótulo explícito
            for label in labels:
                # procura linhas "Loose Price $12.34"
                m = re.search(label + r".{0,20}\$[\d,\.]+", soup.get_text(" ", strip=True), flags=re.I)
                if m:
                    usd = _parse_money_usd(m.group(0))
                    if usd is not None:
                        return usd
            # fallback: procura spans perto de "Loose", "Graded", "New"
            for label in labels:
                el = soup.find(string=re.compile(label, re.I))
                if el:
                    # próximo preço no mesmo bloco
                    block = el.find_parent()
                    if block:
                        m2 = re.search(r"\$[\d,\.]+", block.get_text(" ", strip=True))
                        if m2:
                            return _parse_money_usd(m2.group(0))
            return None

        loose_usd = pick_price_by_label(["Loose Price", "Loose"])
        graded_usd = pick_price_by_label(["Graded Price", "Graded"])
        new_usd = pick_price_by_label(["New Price", "New"])

        trend_pct = _parse_trend_percent(soup)

        return {
            "title": title[:512] if title else "",
            "set_name": set_name[:255] if set_name else "",
            "card_number": card_number[:32] if card_number else "",
            "rarity": rarity[:64] if rarity else "",
            "image_url": image_url[:1024] if image_url else "",
            "release_date": release_date[:64] if release_date else "",
            "loose_brl": _usd_to_brl(loose_usd),
            "graded_brl": _usd_to_brl(graded_usd),
            "new_brl": _usd_to_brl(new_usd),
            "trend_30d_pct": trend_pct,
        }

    def search(self, query: str) -> List[PriceResult]:
        s_url = self._search_url(query)
        soup = self._fetch(s_url)

        rows = soup.select("table#games_table tbody tr")
        results: List[PriceResult] = []

        for tr in rows[:12]:
            link = tr.select_one("td a[href]")
            price_td = tr.select_one("td.price")
            if not (link and price_td):
                continue

            href = (link.get("href") or "").split("?")[0]
            if not href.startswith("http"):
                item_url = "https://www.pricecharting.com" + href
            else:
                item_url = href
            item_url = item_url[:1024]

            # busca detalhes do item
            try:
                details = self._parse_item_detail(item_url)
                loose_brl = details["loose_brl"]
                # se não achou, tenta pelo preço da lista
                if loose_brl is None:
                    usd_list = _parse_money_usd(price_td.get_text(" ", strip=True))
                    loose_brl = _usd_to_brl(usd_list)

                results.append(
                    PriceResult(
                        query=query,
                        source=self.source_name,
                        title=details["title"] or (link.get("title") or link.get_text(" ", strip=True)),
                        url=item_url,
                        price_min_brl=loose_brl or 0.0,
                        price_max_brl=loose_brl or 0.0,
                        # extras:
                        set_name=details["set_name"],
                        card_number=details["card_number"],
                        rarity=details["rarity"],
                        loose_price_brl=details["loose_brl"],
                        graded_price_brl=details["graded_brl"],
                        new_price_brl=details["new_brl"],
                        trend_30d_pct=details["trend_30d_pct"],
                        image_url=details["image_url"],
                        release_date=details["release_date"],
                    )
                )
                # polidez mínima
                time.sleep(0.6)
            except Exception:
                # em caso de erro no detalhe, pelo menos registra a linha básica
                usd_list = _parse_money_usd(price_td.get_text(" ", strip=True))
                loose_brl = _usd_to_brl(usd_list)
                results.append(
                    PriceResult(
                        query=query,
                        source=self.source_name,
                        title=(link.get("title") or link.get_text(" ", strip=True))[:512],
                        url=item_url,
                        price_min_brl=loose_brl or 0.0,
                        price_max_brl=loose_brl or 0.0,
                    )
                )

        return results
