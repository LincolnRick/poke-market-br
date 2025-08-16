# br_market.py
# -----------------------------------------------------------------------------
# Cotação dinâmica em BRL para cartas Pokémon usando Mercado Livre Brasil (MLB).
# v2: queries aprimoradas + relevância tolerante (tokens úteis + número)
# -----------------------------------------------------------------------------

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry  # type: ignore
except Exception:
    Retry = None  # type: ignore

from db import db, Card, Set, PriceHistory

MLB_SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"
HTTP_TIMEOUT = 18
MAX_RESULTS = 50

_NUMBER_SLASH_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


# -----------------------------------------------------------------------------
# HTTP Session com retries
# -----------------------------------------------------------------------------
def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "User-Agent": "collectr-like/1.1 (+mercadolivre-fetch; Python requests)",
        "Connection": "keep-alive",
    })
    if Retry is not None:
        retries = Retry(
            total=3, connect=3, read=3,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    return s


# -----------------------------------------------------------------------------
# Helpers de normalização e tokens
# -----------------------------------------------------------------------------
def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _first_number_part(number: Optional[str]) -> Optional[str]:
    if not number:
        return None
    m = _NUMBER_SLASH_RE.match(number)
    if m:
        return m.group(1)
    return number.strip()


_STOPWORDS = {
    "team", "rocket", "rockets", "trainer", "supporter", "promo", "the",
    "of", "and", "de", "da", "do", "ex", "gx", "v", "vstar", "vmax", "lv", "x"
}


def _useful_tokens(name: str) -> List[str]:
    """
    Extrai tokens 'úteis' do nome (sem acento, minúsculo), removendo stopwords e
    símbolos. Ex.: "Team Rocket's Mewtwo ex" -> ["mewtwo", "ex"] (ex fica, mas
    não conta como token principal).
    """
    base = _strip_accents(name.lower())
    tokens = re.findall(r"[a-z0-9]+", base)
    # mantemos "ex", "gx", "v*" para reforço, mas marcamos principais sem eles
    return [t for t in tokens if len(t) > 1]


def _principal_tokens(tokens: List[str]) -> List[str]:
    """Tokens que realmente identificam o Pokémon (remove stopwords do conjunto)."""
    return [t for t in tokens if t not in _STOPWORDS]


_PT_SET_SYNONYMS = {
    # Pequeno dicionário útil; adicione conforme for usando
    "Destined Rivals": "Rivais Predestinados",
    "Paradox Rift": "Fenda Paradoxa",
    "Obsidian Flames": "Chamas Obsidianas",
    "Paldean Fates": "Destinos de Paldea",
    "Scarlet & Violet": "Escarlate e Violeta",
}


def _build_query_variants(card: Card) -> List[str]:
    """
    Gera consultas em camadas. Inclui:
      - nome simplificado + número
      - set EN e PT (quando conhecido)
      - versões 'pokemon', 'tcg' e mínimas
    """
    name = (card.name or "").strip()
    set_name = (card.set.name if card.set else "") or ""
    set_pt = _PT_SET_SYNONYMS.get(set_name, "")
    n_only = _first_number_part(card.number) or ""

    # nome simplificado para evitar 'team/rocket's' atrapalhando
    name_simple = re.sub(r"[’'`]", " ", name)
    name_simple = re.sub(r"\s+", " ", name_simple).strip()

    def uniq_tokens(text: str) -> List[str]:
        uniq, seen = [], set()
        for t in text.split():
            k = _strip_accents(t.lower())
            if k and k not in seen:
                seen.add(k)
                uniq.append(t)
        return uniq

    variants = []

    # Combinações mais fortes (nome + número + set PT/EN)
    if name_simple and n_only:
        variants.append(" ".join(uniq_tokens(f"pokemon tcg {name_simple} {set_pt} {n_only}")))
        variants.append(" ".join(uniq_tokens(f"pokemon {name_simple} {n_only}")))
        if set_name:
            variants.append(" ".join(uniq_tokens(f"{name_simple} {set_name} {n_only}")))
        if set_pt:
            variants.append(" ".join(uniq_tokens(f"{name_simple} {set_pt} {n_only}")))

    # fallback por nome + número
    if name_simple and n_only:
        variants.append(" ".join(uniq_tokens(f"{name_simple} {n_only}")))

    # fallback por nome simples
    if name_simple:
        variants.append(" ".join(uniq_tokens(f"pokemon tcg {name_simple}")))
        variants.append(" ".join(uniq_tokens(f"{name_simple}")))

    # fallback mínimo só por número (útil para cartas muito óbvias)
    if n_only:
        variants.append(str(n_only))

    # remove duplicatas e vazios mantendo ordem
    seen, out = set(), []
    for q in variants:
        qn = q.strip()
        if not qn:
            continue
        key = _strip_accents(qn.lower())
        if key not in seen:
            seen.add(key)
            out.append(qn)
    return out


def _percentiles(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac)


def _iqr_filter(prices: List[float]) -> Tuple[List[float], Dict[str, float]]:
    if not prices:
        return [], {"q1": 0.0, "q3": 0.0, "iqr": 0.0, "low": 0.0, "high": 0.0}
    vals = sorted(float(p) for p in prices if p is not None)
    q1 = _percentiles(vals, 0.25)
    q3 = _percentiles(vals, 0.75)
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    cleaned = [p for p in vals if (p >= low and p <= high)]
    return cleaned, {"q1": q1, "q3": q3, "iqr": iqr, "low": low, "high": high}


# -----------------------------------------------------------------------------
# MLB fetch + relevância
# -----------------------------------------------------------------------------
def _fetch_mlb_raw(session: requests.Session, query: str, limit: int = MAX_RESULTS) -> List[Dict]:
    params = {
        "q": query,
        "limit": max(10, min(limit, MAX_RESULTS)),
    }
    r = session.get(MLB_SEARCH_URL, params=params, timeout=HTTP_TIMEOUT)
    try:
        data = r.json()
    except Exception:
        return []
    results = data.get("results", [])
    return results if isinstance(results, list) else []


def _normalize_listing(r: Dict) -> Optional[Dict]:
    try:
        price = float(r.get("price"))
    except Exception:
        return None
    currency = r.get("currency_id")
    if currency and currency != "BRL":
        return None
    return {
        "listing_id": r.get("id"),
        "title": r.get("title") or "",
        "price": price,
        "currency": currency or "BRL",
        "permalink": r.get("permalink") or "",
        "thumbnail": r.get("thumbnail") or r.get("thumbnail_id") or "",
        "condition": r.get("condition") or "",
        "seller_id": (r.get("seller") or {}).get("id"),
        "shipping": r.get("shipping") or {},
        "domain_id": r.get("domain_id") or "",
        "catalog_listing": bool(r.get("catalog_listing")),
    }


def _title_relevant(title: str, name_tokens: List[str], principal: List[str], number_token: Optional[str]) -> bool:
    """Aceita se contiver o número OU >=2 tokens úteis (com pelo menos 1 principal)."""
    t = _strip_accents(title.lower())
    if number_token and number_token in t:
        return True
    hits = sum(1 for tok in name_tokens if tok in t)
    main_hits = sum(1 for tok in principal if tok in t)
    if hits >= 2 and main_hits >= 1:
        return True
    # fallback ainda mais tolerante para nomes longos: 1 principal já conta
    if main_hits >= 1 and hits >= 1:
        return True
    return False


def fetch_mlb_listings_for_card(card_id: int, limit: int = MAX_RESULTS) -> Dict:
    """
    Busca listagens MLB para a carta. Nunca lança exceção.
    """
    card = Card.query.get(card_id)
    if not card:
        return {"query": "", "attempts": [], "raw_count": 0, "listings": [], "error": "card_id inválido"}

    session = _build_session()
    attempts = _build_query_variants(card)

    name_tokens = _useful_tokens(card.name or "")
    principal = _principal_tokens(name_tokens)
    n_only = _first_number_part(card.number) or None

    last_error: Optional[str] = None
    best_query = ""
    best_raw: List[Dict] = []
    listings: List[Dict] = []

    for q in attempts:
        try:
            raw = _fetch_mlb_raw(session, q, limit=limit)
            tmp = []
            for r in raw:
                norm = _normalize_listing(r)
                if not norm:
                    continue
                if _title_relevant(norm["title"], name_tokens, principal, n_only):
                    tmp.append(norm)

            if tmp:
                best_query = q
                best_raw = raw
                listings = tmp
                break

            if not best_raw and raw:
                best_query = q
                best_raw = raw
        except Exception as e:
            last_error = f"falha em '{q}': {e}"
            continue

    return {
        "query": best_query or (attempts[0] if attempts else ""),
        "attempts": attempts,
        "raw_count": len(best_raw),
        "listings": listings,
        "error": last_error,
    }


# -----------------------------------------------------------------------------
# Cálculo da média dinâmica
# -----------------------------------------------------------------------------
def compute_dynamic_price_brl(listings: List[Dict]) -> Dict:
    prices = [l["price"] for l in listings if "price" in l and l["price"] is not None]
    raw_count = len(prices)
    cleaned, stats = _iqr_filter(prices)

    if cleaned:
        vals_sorted = sorted(cleaned)
        p25 = _percentiles(vals_sorted, 0.25)
        median = _percentiles(vals_sorted, 0.5)
        p75 = _percentiles(vals_sorted, 0.75)
        low3 = vals_sorted[:3]
        low3_avg = round(sum(low3) / max(1, len(low3)), 2)
    else:
        p25 = median = p75 = low3_avg = 0.0

    return {
        "count": len(cleaned),
        "raw_count": raw_count,
        "median": round(median, 2),
        "p25": round(p25, 2),
        "p75": round(p75, 2),
        "low3_avg": round(low3_avg, 2),
        "filters": stats,
    }


# -----------------------------------------------------------------------------
# Orquestração: busca + cálculo + (opcional) histórico
# -----------------------------------------------------------------------------
def refresh_br_price(card_id: int, *, save_history: bool = True) -> Dict:
    """
    Executa a busca no MLB e calcula a cotação dinâmica.
    Nunca levanta exceção: retorna 'dynamic_brl=None' quando indisponível.
    """
    bundle = fetch_mlb_listings_for_card(card_id, limit=MAX_RESULTS)
    listings = bundle.get("listings", [])
    error = bundle.get("error")

    if not listings:
        return {
            "card_id": card_id,
            "query": bundle.get("query", ""),
            "attempts": bundle.get("attempts", []),
            "dynamic_brl": None,
            "low3_avg": None,
            "stats": None,
            "sample": [],
            "error": error or "sem resultados relevantes do MLB",
        }

    stats = compute_dynamic_price_brl(listings)
    dynamic_brl = stats["median"]
    low3_avg = stats["low3_avg"]

    try:
        if save_history and dynamic_brl and dynamic_brl > 0:
            ph = PriceHistory(
                card_id=card_id,
                price=float(dynamic_brl),
                source="MLB:dynamic",
                captured_at=datetime.utcnow(),
            )
            db.session.add(ph)
            db.session.commit()
    except Exception as e:
        note = f"erro ao salvar histórico: {e}"
        error = f"{error} | {note}" if error else note

    return {
        "card_id": card_id,
        "query": bundle.get("query", ""),
        "attempts": bundle.get("attempts", []),
        "dynamic_brl": dynamic_brl,
        "low3_avg": low3_avg,
        "stats": stats,
        "sample": listings[:6],
        "error": error,
    }
