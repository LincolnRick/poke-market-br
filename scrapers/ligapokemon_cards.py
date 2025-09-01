"""LigaPokemon cards scraper.

Este módulo oferece função `fetch_set_cards` que, dado um `edid` da Liga
Pokémon, busca a lista de cartas daquele set e retorna uma lista de
 dicionários normalizados contendo informações como nome, número, tipo,
raridade e demais campos disponíveis na página de detalhe.

A implementação tenta ser tolerante a mudanças leves no HTML, utilizando
heurísticas para localizar os dados. Todas as requisições usam cabeçalhos
similares aos outros scrapers e pequenas pausas entre os requests para
reduzir o risco de bloqueio por parte do servidor.
"""

from __future__ import annotations

import re
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Cabeçalhos semelhantes aos utilizados em outros scrapers da Liga Pokémon.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.ligapokemon.com.br/?view=cards/search",
    "Connection": "close",
}

SEARCH_URL = "https://www.ligapokemon.com.br/?view=cards/search&edid={edid}"
CARD_LINK_SELECTOR = 'a[href*="view=cards/card"]'
_field_re = re.compile(r"[^a-z0-9]+")
_space_re = re.compile(r"\s+")


def _clean(text: str) -> str:
    """Normaliza espaços em branco."""
    return _space_re.sub(" ", (text or "")).strip()


def _norm_key(text: str) -> str:
    """Converte label em snake_case para uso como chave de dict."""
    return _field_re.sub("_", _clean(text).lower()).strip("_")


def _parse_detail(url: str, timeout: int = 30) -> Dict[str, str]:
    """Extrai informações de uma página de detalhe de carta."""
    data: Dict[str, str] = {"link": url}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return data

    soup = BeautifulSoup(resp.text, "html.parser")

    # Nome da carta em heading
    h = soup.find(["h1", "h2", "h3"])
    if h and h.text:
        data["name"] = _clean(h.text)

    # Tabelas chave-valor comuns no site
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            key = _norm_key(cells[0].get_text())
            val = _clean(cells[1].get_text())
            if key and val:
                data[key] = val

    return data


def fetch_set_cards(edid: str, delay_s: float = 0.8) -> List[Dict[str, str]]:
    """Busca todas as cartas de um *set* (edid).

    Parameters
    ----------
    edid: str
        Identificador da edição no site da Liga Pokémon.
    delay_s: float
        Pausa entre requisições de detalhes para evitar bloqueios.

    Returns
    -------
    List[Dict[str, str]]
        Lista de dicionários com os campos normalizados.
    """
    url = SEARCH_URL.format(edid=edid)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    cards: List[Dict[str, str]] = []
    seen: set[str] = set()

    for a in soup.select(CARD_LINK_SELECTOR):
        href = a.get("href") or ""
        abs_url = urljoin(url, href)
        if not abs_url or abs_url in seen:
            continue
        seen.add(abs_url)
        cards.append(_parse_detail(abs_url))
        time.sleep(delay_s)

    return cards


__all__ = ["fetch_set_cards"]
