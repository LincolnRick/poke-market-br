# liga_market.py
# -----------------------------------------------------------------------------
# Liga Pokémon (BR) — captura de preços com estatísticas (min/avg/max)
# v6:
#   - Usa o número de coleção completo (X/Y) nas buscas quando disponível
#   - Em queries numéricas (ex.: "84" ou "182/182"), envia tipo=1 (ex.: ?card=182/182&tipo=1)
#   - Valida candidatos pelo número do título: exige bater X/Y (se ambos conhecidos) ou X (se só X)
#   - Mantém tradução de formas regionais e sinônimos EN→PT de sets
# -----------------------------------------------------------------------------

from __future__ import annotations

import re
import unicodedata
from statistics import mean
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry  # type: ignore
except Exception:
    Retry = None  # type: ignore

from db import db, Card, Set, PriceHistory

BASE = "https://www.ligapokemon.com.br/"
SEARCH_URL = urljoin(BASE, "?view=cards/search")
HTTP_TIMEOUT = 18

# -------------------- Regex/const --------------------
BRL_RE = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", re.IGNORECASE)
NUM_SLASH = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$", re.ASCII)
ONLY_NUM = re.compile(r"^\s*\d+\s*$", re.ASCII)
CARD_LINK_RE = re.compile(r'href="([^"]*view=cards/card[^"]+)"', re.IGNORECASE)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TITLE_NUM_RE = re.compile(r"\((\d+)\s*/\s*(\d+)\)")  # ex.: "(084/108)"

# -------------------- HTTP session -------------------
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "User-Agent": "collectr/1.6 liga-scraper (+requests)",
        "Connection": "keep-alive",
    })
    if Retry:
        r = Retry(
            total=3, connect=3, read=3,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        ad = HTTPAdapter(max_retries=r, pool_connections=10, pool_maxsize=12)
        s.mount("https://", ad); s.mount("http://", ad)
    return s

# -------------------- Normalização -------------------
def _strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def _print_parts(number: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Retorna (X, Y, "X/Y" normalizado) se number contiver barra; se apenas X, retorna (X, None, None).
    """
    if not number:
        return None, None, None
    raw = (number or "").strip()
    m = NUM_SLASH.match(raw)
    if m:
        try:
            x = int(m.group(1)); y = int(m.group(2))
            return x, y, f"{x}/{y}"
        except Exception:
            return None, None, None
    try:
        x = int(raw)
        return x, None, None
    except Exception:
        return None, None, None

# Nome EN -> BR (formas regionais)
def _regional_to_br_label(name: str) -> str:
    m = re.match(r"(?i)^(Alolan|Galarian|Hisuian|Paldean)\s+(.+)$", (name or "").strip())
    if m:
        specie = m.group(2).strip()
        region = m.group(1).lower()
        suffix = {
            "alolan": "de Alola",
            "galarian": "de Galar",
            "hisuian": "de Hisui",
            "paldean": "de Paldea",
        }[region]
        return f"{specie} {suffix}"
    return name

# Sinônimos de sets EN -> PT (ampliável)
SET_PT = {
    "Team Up": "União de Aliados",
    "Lost Origin": "Origem Perdida",
    "Silver Tempest": "Tempestade Prateada",
    "Evolving Skies": "Céus em Evolução",
    "Chilling Reign": "Reinado Arrepiante",
    "Brilliant Stars": "Estrelas Radiantes",
    "Astral Radiance": "Radiação Astral",
    "Battle Styles": "Estilos de Batalha",
    "Vivid Voltage": "Voltagem Vívida",
    "Crown Zenith": "Zênite da Coroa",
    "Obsidian Flames": "Chamas Obsidianas",
    "Paldean Fates": "Destinos de Paldea",
    "Scarlet & Violet": "Escarlate e Violeta",
    "Paradox Rift": "Fenda Paradoxa",
    "Hidden Fates": "Destinos Ocultos",
    "Shining Fates": "Destinos Brilhantes",
    "Ancient Origins": "Origens Ancestrais",
    "Unified Minds": "Mentes Unidas",
    "Cosmic Eclipse": "Eclipse Cósmico",
    "Destined Rivals": "Rivais Predestinados",
}

def _uniq_tokens(text: str) -> List[str]:
    out, seen = [], set()
    for t in text.split():
        k = _strip_acc(t.lower())
        if k and k not in seen:
            seen.add(k); out.append(t)
    return out

def _build_queries(card: Card) -> List[str]:
    name = (card.name or "").strip()
    name_pt = _regional_to_br_label(name)
    set_en = (card.set.name if card.set else "") or ""
    set_pt = SET_PT.get(set_en, set_en)  # se não souber, usa EN
    x, y, full = _print_parts(card.number)

    base_variants: List[str] = []

    # Preferência: com número completo X/Y
    if full:
        if name_pt: base_variants.append(" ".join(_uniq_tokens(f"{name_pt} {set_pt} {full}")))
        if name:    base_variants.append(" ".join(_uniq_tokens(f"{name} {set_en} {full}")))
        base_variants.append(full)

    # Depois: apenas numerador X
    if x is not None:
        if name_pt: base_variants.append(" ".join(_uniq_tokens(f"{name_pt} {set_pt} {x}")))
        if name:    base_variants.append(" ".join(_uniq_tokens(f"{name} {set_en} {x}")))
        base_variants.append(str(x))

    # Por fim: nomes (PT e EN) sem número, como fallback
    if name_pt: base_variants.append(" ".join(_uniq_tokens(name_pt)))
    if name:    base_variants.append(" ".join(_uniq_tokens(name)))

    # Dedup mantendo ordem
    out, seen = [], set()
    for q in base_variants:
        key = _strip_acc(q.lower())
        if key and key not in seen:
            seen.add(key); out.append(q)
    return out

# -------------------- HTML helpers -------------------
def _fetch_html(s: requests.Session, url: str, params: Optional[Dict[str,str]] = None) -> Optional[str]:
    try:
        r = s.get(url, params=params or {}, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.text or ""
    except Exception:
        return None

def _find_card_links(search_html: str, limit: int = 20) -> List[str]:
    links = []
    for m in CARD_LINK_RE.finditer(search_html or ""):
        href = m.group(1)
        full = urljoin(BASE, href)
        if full not in links:
            links.append(full)
        if len(links) >= limit:
            break
    return links

def _slice_sellers(html: str) -> str:
    if not html:
        return ""
    low = html.lower()
    idx = low.find("lojas vendendo")
    if idx == -1:
        return html
    return html[idx: idx + 25000]

def _parse_brl(token: str) -> Optional[float]:
    try:
        return float(token.replace(".","").replace(",","."))
    except Exception:
        return None

def _extract_prices(html: str) -> List[float]:
    vals: List[float] = []
    for m in BRL_RE.finditer(html or ""):
        v = _parse_brl(m.group(1))
        if v and v > 0:
            vals.append(v)
    return vals

def _title_text(html: str) -> str:
    m = TITLE_RE.search(html or "")
    if not m:
        return ""
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    return title

def _title_print_tuple(html: str) -> Tuple[Optional[int], Optional[int]]:
    """Extrai (X,Y) do título, ex.: '(084/108)' -> (84,108)."""
    title = _title_text(html)
    m = TITLE_NUM_RE.search(title)
    if not m:
        return None, None
    try:
        return int(m.group(1)), int(m.group(2))
    except Exception:
        return None, None

def _norm_tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _strip_acc((s or "").lower())) if len(t) > 1]

# -------------------- Scoring -------------------
def _score_detail_page(html: str, name_tokens: List[str], set_tokens: List[str]) -> int:
    """Pontuação por nome e set (número é validado como regra separada)."""
    txt = _strip_acc(_title_text(html).lower())[:300]
    score = 0
    if not txt:
        return score
    score += sum(1 for t in name_tokens if t in txt) * 2
    score += sum(1 for t in set_tokens if t in txt) * 1
    return score

# -------------------- Pública: busca + estatísticas -------------------
def fetch_liga_prices_for_card(card_id: int) -> Dict:
    """
    Busca preços na Liga a partir da PÁGINA da carta (quando encontrada).
    - Se conhecemos X/Y, só aceitamos páginas cujo título contenha exatamente (X/Y).
    - Se conhecemos apenas X, exigimos que o primeiro número do título seja X.
    """
    card = db.session.get(Card, card_id)
    if not card:
        return {
            "attempts": [], "candidate_urls": [], "used_url": "",
            "prices": [], "min": None, "avg": None, "max": None, "count": 0,
            "error": "card_id inválido"
        }

    name = (card.name or "").strip()
    name_pt = _regional_to_br_label(name)
    set_en = (card.set.name if card.set else "") or ""
    set_pt = SET_PT.get(set_en, set_en)

    x_known, y_known, full_known = _print_parts(card.number)

    # tokens para score
    name_tokens = _norm_tokens(name_pt or name)
    set_tokens  = _norm_tokens(set_pt or set_en)

    s = _session()
    attempts = _build_queries(card)

    best_url = ""
    best_score = -1
    prices: List[float] = []
    last_error: Optional[str] = None
    all_candidates: List[str] = []
    rejected_number: int = 0

    for q in attempts:
        # 1) página de busca — adiciona tipo=1 se query é numérica (ex.: "84" ou "182/182")
        params = {"card": q}
        if NUM_SLASH.match(q) or ONLY_NUM.match(q):
            params["tipo"] = "1"

        search_html = _fetch_html(s, SEARCH_URL, params=params)
        if not search_html:
            last_error = "falha ao obter HTML da busca"
            continue

        # 2) todos os links de carta da página
        candidates = _find_card_links(search_html, limit=20)
        for url in candidates:
            if url not in all_candidates:
                all_candidates.append(url)

        # 3) abre e avalia os candidatos; valida número do título
        for url in candidates[:12]:
            detail_html = _fetch_html(s, url)
            if not detail_html:
                last_error = "falha ao abrir página da carta"
                continue

            t_x, t_y = _title_print_tuple(detail_html)

            # Regras de número
            if x_known is not None and y_known is not None:
                # precisamos de X/Y exatos
                if t_x is None or t_y is None or t_x != x_known or t_y != y_known:
                    rejected_number += 1
                    continue
            elif x_known is not None:
                # pelo menos X (primeiro número) deve bater
                if t_x is None or t_x != x_known:
                    rejected_number += 1
                    continue
            # se não conhecemos número, não aplicamos filtro por número

            score = _score_detail_page(detail_html, name_tokens, set_tokens)
            sellers = _slice_sellers(detail_html)
            p = _extract_prices(sellers)

            if p and score >= best_score:
                best_score = score
                best_url = url
                prices = p

        # se já achamos preços válidos, paramos
        if prices:
            break

    if not prices:
        return {
            "attempts": attempts,
            "candidate_urls": all_candidates[:20],
            "used_url": "",
            "prices": [],
            "min": None, "avg": None, "max": None, "count": 0,
            "score": -1 if (x_known is not None) else best_score,
            "rejected_number": rejected_number,
            "error": last_error or "sem preços detectados na Liga",
        }

    p_min = min(prices); p_max = max(prices); p_avg = round(mean(prices), 2)
    return {
        "attempts": attempts,
            "candidate_urls": all_candidates[:20],
            "used_url": best_url,
            "prices": prices[:40],
            "min": p_min,
            "avg": p_avg,
            "max": p_max,
            "count": len(prices),
            "score": best_score,
            "rejected_number": rejected_number,
            "error": None,
    }

# -------------------- Orquestração + snapshot -------------------
def refresh_liga_min_price(card_id: int, *, save_history: bool = True) -> Dict:
    """
    Compatível com /price/refresh_liga.
    Salva snapshot só do mínimo (source='LIGA:min'), mas retorna estatísticas completas.
    """
    bundle = fetch_liga_prices_for_card(card_id)
    liga_min = bundle.get("min")
    liga_avg = bundle.get("avg")
    liga_max = bundle.get("max")
    count = bundle.get("count", 0)

    # snapshot (mínimo)
    try:
        if save_history and liga_min and liga_min > 0:
            ph = PriceHistory(
                card_id=card_id,
                price=float(liga_min),
                source="LIGA:min",
                captured_at=datetime.utcnow(),
            )
            db.session.add(ph); db.session.commit()
    except Exception as e:
        err = bundle.get("error")
        bundle["error"] = f"{err} | erro ao salvar histórico: {e}" if err else f"erro ao salvar histórico: {e}"

    return {
        "card_id": card_id,
        "liga_min": liga_min,
        "liga_avg": liga_avg,
        "liga_max": liga_max,
        "count": count,
        "used_url": bundle.get("used_url", ""),
        "candidate_urls": bundle.get("candidate_urls", []),
        "attempts": bundle.get("attempts", []),
        "prices": bundle.get("prices", []),
        "score": bundle.get("score"),
        "rejected_number": bundle.get("rejected_number", 0),
        "error": bundle.get("error"),
    }
