# scrapers/ligapokemon_html.py
# -*- coding: utf-8 -*-
"""
LigaPokemon (HTML) → listagens ativas (leilão / preço fixo) por palavra-chave.

Páginas:
- Lista:  https://www.ligapokemon.com.br/?view=leilao/listar&tela=grid&txt_carta=<query>
- Detalhe: https://www.ligapokemon.com.br/?view=leilao/view&id=<id>

Notas do site:
- A lista mostra “R$ …” e textos como “Finaliza em …”, “Preço Fixo”.         (*)
- A busca é sensível a separadores; “4/102” raramente retorna. Gera variantes: 4 102, 4, e só nome. (*)

(*) Evidências públicas: páginas de lista (grid/tb) e de detalhe da Liga. 
"""

from __future__ import annotations

import re
import time
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper, PriceResult

BASE_URL = "https://www.ligapokemon.com.br/"
LIST_PATH = "?view=leilao/listar"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125 Safari/537.36"
)
HDRS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.ligapokemon.com.br/?view=leilao/listar",
    "Connection": "close",
}

_price_re = re.compile(r"R\$\s*([\d\.\,]+)")
_spaces_re = re.compile(r"\s+")


def _to_brl_float(txt: str) -> Optional[float]:
    if not txt:
        return None
    m = _price_re.search(txt)
    if not m:
        return None
    raw = m.group(1).strip()
    # "1.234,56" (BR) -> 1234.56
    raw = raw.replace(".", "").replace(",", ".")
    try:
        v = float(raw)
        return round(v, 2) if v > 0 else None
    except Exception:
        return None


def _clean(s: str) -> str:
    return _spaces_re.sub(" ", (s or "")).strip()


def _variants(q: str) -> List[str]:
    """
    Gera variações tolerantes para a busca da Liga.
    Ex.: "Charizard 4/102" → ["Charizard 4/102", "Charizard 4 102", "Charizard 4", "Charizard"]
    """
    s = (q or "").strip()
    if not s:
        return []
    out: List[str] = []
    seen = set()

    def add(x: Optional[str]):
        if not x:
            return
        x = _clean(x)
        if x and x not in seen:
            seen.add(x)
            out.append(x)

    add(s)
    add(re.sub(r"[/\-]+", " ", s))  # troca separador por espaço

    m = re.search(r"(\d+)\s*[/\-]\s*(\d+)", s)
    if m:
        n1 = m.group(1)
        add(re.sub(r"(\d+)\s*[/\-]\s*(\d+)", n1, s))

    # só nome (remove números e parênteses)
    name_only = re.sub(r"[\(\)\[\]#]", " ", s)
    name_only = re.sub(r"\d+(\s*[/\-]\s*\d+)?", " ", name_only)
    add(name_only)

    return out[:5]


def _build_list_url(query: str, view: str = "grid") -> str:
    params = {
        "view": "leilao/listar",
        "txt_carta": query.strip(),
        "tela": view,  # "grid" ou "tb" (ambas funcionam)
    }
    return BASE_URL + "?" + urlencode(params, doseq=True)


def _closest_tile_text(a_tag) -> str:
    """
    Sobe alguns níveis e captura o texto do 'tile' para achar preço/labels.
    """
    node = a_tag
    for _ in range(6):
        if node and node.parent:
            node = node.parent
        else:
            break
        txt = _clean(node.get_text(" ", strip=True))
        # heurística: se contém "R$" ou "Finaliza" ou "Preço Fixo", já serve
        if "R$" in txt or "Finaliza" in txt or "Preço Fixo" in txt:
            return txt
    # fallback: texto direto do link
    return _clean(a_tag.get_text(" ", strip=True))


def _detail_price(url: str, timeout: int = 15) -> Tuple[Optional[float], Optional[str]]:
    """
    Abre a página de detalhe e tenta extrair o preço visível.
    Retorna (preco_brl, titulo) ou (None, None).
    """
    try:
        r = requests.get(url, headers=HDRS, timeout=timeout)
        r.raise_for_status()
    except Exception:
        return None, None

    soup = BeautifulSoup(r.text, "html.parser")
    txt = _clean(soup.get_text(" ", strip=True))
    price = _to_brl_float(txt)
    # título: usa <title> ou heading
    title = None
    ttag = soup.find("title")
    if ttag and ttag.text:
        title = _clean(ttag.text)
    if not title:
        h = soup.find(["h1", "h2", "h3"])
        if h and h.text:
            title = _clean(h.text)
    return price, title


class LigaPokemonHTMLScraper(BaseScraper):
    source_name = "ligapokemon"

    def search(self, query: str) -> List[PriceResult]:
        q = (query or "").strip()
        if len(q) < 2:
            return []

        results: List[PriceResult] = []
        seen_urls = set()

        # Tenta variações; para cada variação, consulta "grid" e, se vazio, "tb"
        for qv in _variants(q):
            found_this_variant = 0
            for view in ("grid", "tb"):
                url = _build_list_url(qv, view=view)
                try:
                    r = requests.get(url, headers=HDRS, timeout=20)
                    r.raise_for_status()
                except Exception as e:
                    print(f"[ligapokemon] GET erro: {e}")
                    continue

                soup = BeautifulSoup(r.text, "html.parser")
                anchors = soup.select('a[href*="view=leilao/view"]')  # links dos leilões
                if not anchors:
                    # nenhuma âncora → tenta próxima variação/visualização
                    time.sleep(0.1)
                    continue

                for a in anchors:
                    href = a.get("href") or ""
                    if "view=leilao/view" not in href:
                        continue
                    abs_url = urljoin(BASE_URL, href)
                    if abs_url in seen_urls:
                        continue

                    block_text = _closest_tile_text(a)
                    title = _clean(a.get_text(" ").strip())
                    if not title:
                        title = block_text

                    # Preço no tile
                    price = _to_brl_float(block_text)

                    # Sinaliza tipo
                    kind = "leilao" if "Finaliza" in block_text or "Lance" in block_text else "fixo" if "Preço Fixo" in block_text else None
                    if kind and title:
                        title = f"{title} — {kind}"

                    # Se não achou preço no tile, abre o detalhe (só para poucos itens)
                    if price is None and found_this_variant < 6:
                        d_price, d_title = _detail_price(abs_url)
                        if d_price:
                            price = d_price
                            if d_title:
                                title = d_title

                    if price is None:
                        continue

                    pr = PriceResult(
                        query=q,  # mantém o termo original
                        source=self.source_name,
                        title=(title or f"Leilão - {q}")[:512],
                        url=abs_url,
                        price_min_brl=price,
                        price_max_brl=price,
                    ).clamp()

                    results.append(pr)
                    seen_urls.add(abs_url)
                    found_this_variant += 1

                    if len(results) >= 60:
                        break

                if len(results) >= 60:
                    break

                time.sleep(0.15)  # backoff entre views

            # Se já conseguiu bastante coisa com essa variação, pode encerrar cedo
            if len(results) >= 40:
                break

            time.sleep(0.2)  # backoff entre variações

        # Ordena por preço crescente
        results.sort(key=lambda x: (x.price_min_brl or 9e12))
        return results
