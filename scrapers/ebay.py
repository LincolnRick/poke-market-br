# scrapers/ebay.py
"""
eBay Browse API → resultados de busca com preço min/máx normalizados em BRL.
Agora cada resultado inclui metadados de conversão FX (moeda de origem e taxa),
para exibirmos um badge no front (ex.: USD→BRL 5.27).

Requisitos de ambiente:
  - EBAY_CLIENT_ID, EBAY_CLIENT_SECRET (obrigatórios)
  - EBAY_SCOPE (opcional; default: https://api.ebay.com/oauth/api_scope)
  - EBAY_MP_ID (opcional; ex.: EBAY_US, EBAY_GB, EBAY_DE ...; default: EBAY_US)
"""
from __future__ import annotations

import os
import re
import time
from typing import List, Optional, Dict, Any, Tuple

import requests

from .base import BaseScraper, PriceResult
from .fx import convert as fx_convert, get_rate as fx_get_rate

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

_DEFAULT_SCOPE = "https://api.ebay.com/oauth/api_scope"
_DEFAULT_MP = "EBAY_US"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)


class _TokenStore:
    """Cache simples em memória para o token OAuth."""
    access_token: Optional[str] = None
    exp_ts: float = 0.0
    last_error: Optional[str] = None

    @classmethod
    def get(cls) -> Optional[str]:
        if not cls.access_token:
            return None
        if time.time() >= cls.exp_ts:
            return None
        return cls.access_token

    @classmethod
    def set(cls, token: str, expires_in: int) -> None:
        cls.last_error = None
        cls.access_token = token
        cls.exp_ts = time.time() + max(0, int(expires_in) - 60)


def _get_oauth_token() -> Optional[str]:
    cached = _TokenStore.get()
    if cached:
        return cached

    cid = os.getenv("EBAY_CLIENT_ID")
    csec = os.getenv("EBAY_CLIENT_SECRET")
    scope = os.getenv("EBAY_SCOPE", _DEFAULT_SCOPE)

    if not cid or not csec:
        _TokenStore.last_error = "EBAY_CLIENT_ID/EBAY_CLIENT_SECRET ausentes."
        return None

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": _UA,
    }
    data = {
        "grant_type": "client_credentials",
        "scope": scope,
    }

    try:
        resp = requests.post(
            OAUTH_URL,
            headers=headers,
            data=data,
            auth=(cid, csec),
            timeout=20,
        )
        resp.raise_for_status()
        j = resp.json()
        token = j.get("access_token")
        expires_in = j.get("expires_in", 0)
        if token:
            _TokenStore.set(token, int(expires_in or 0))
            return token
        _TokenStore.last_error = f"OAuth sem token (payload={j})"
    except Exception as e:
        _TokenStore.last_error = f"OAuth error: {e}"
        return None
    return None


def _variants(q: str) -> List[str]:
    """Gera variações tolerantes: troca separadores, mantém só primeiro número etc."""
    s = (q or "").strip()
    if not s:
        return []
    out: List[str] = []
    seen = set()

    def add(x: Optional[str]):
        if not x:
            return
        x = re.sub(r"\s+", " ", x).strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)

    add(s)
    # 4/102 -> 4 102
    add(re.sub(r"[/\-]+", " ", s))

    m = re.search(r"(\d+)\s*[/\-]\s*(\d+)", s)
    if m:
        n1 = m.group(1)
        add(re.sub(r"(\d+)\s*[/\-]\s*(\d+)", n1, s))

    # só o nome (remove números e parênteses)
    name_only = re.sub(r"[\(\)\[\]#]", " ", s)
    name_only = re.sub(r"\d+(\s*[/\-]\s*\d+)?", " ", name_only)
    add(name_only)

    return out[:5]


def _search_once(q: str, token: str, marketplace: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    params = {
        "q": q,
        "filter": "buyingOptions:{FIXED_PRICE,AUCTION}",
        "fieldgroups": "ASPECTS",
        "limit": "50",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": _UA,
        "X-EBAY-C-MARKETPLACE-ID": marketplace,
    }
    try:
        r = requests.get(BROWSE_SEARCH_URL, headers=headers, params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        items = data.get("itemSummaries") or []
        return items, None
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


def _to_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if v > 0 else None
    except Exception:
        return None


def _to_brl_with_meta(value: Any, currency: Optional[str]) -> Tuple[Optional[float], Optional[str], Optional[float]]:
    """
    Converte qualquer moeda retornada pelo eBay para BRL.
    Retorna (valor_em_brl, moeda_origem, taxa_usada) — se já for BRL, moeda_origem=None.
    """
    v = _to_float(value)
    if v is None:
        return None, None, None
    ccy = (currency or "").upper().strip()
    if not ccy:
        return None, None, None
    if ccy == "BRL":
        return v, None, None
    rate = fx_get_rate(ccy, "BRL")
    if not rate or rate <= 0:
        return None, None, None
    return round(v * rate, 4), ccy, float(rate)


def _coalesce_price_fields(it: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrai possíveis preços do item_summary (BIN, lance atual, etc.).
    Retorna lista de dicts {value, currency}.
    """
    out: List[Dict[str, Any]] = []
    p = it.get("price") or it.get("currentPrice")
    if isinstance(p, dict) and "value" in p:
        out.append({"value": p.get("value"), "currency": p.get("currency")})
    cb = it.get("currentBidPrice")
    if isinstance(cb, dict) and "value" in cb:
        out.append({"value": cb.get("value"), "currency": cb.get("currency")})
    return out


class EbayScraper(BaseScraper):
    source_name = "ebay"

    def search(self, query: str) -> List[PriceResult]:
        if not query or len(query.strip()) < 2:
            return []

        token = _get_oauth_token()
        if not token:
            # Falha de credencial → sem resultados
            return []

        marketplace = os.getenv("EBAY_MP_ID", _DEFAULT_MP).strip().upper() or _DEFAULT_MP

        results: List[PriceResult] = []

        for qv in _variants(query):
            items, err = _search_once(qv, token, marketplace)
            if err:
                time.sleep(0.2)
                continue

            for it in items:
                title = (it.get("title") or "").strip()
                url = it.get("itemWebUrl") or it.get("itemAffiliateWebUrl") or ""
                if not title or not url:
                    continue

                price_candidates = _coalesce_price_fields(it)

                brl_vals: List[float] = []
                fx_from: Optional[str] = None
                fx_rate: Optional[float] = None

                for pc in price_candidates:
                    brl, from_ccy, rate = _to_brl_with_meta(pc.get("value"), pc.get("currency"))
                    if brl is not None and brl > 0:
                        brl_vals.append(brl)
                        # guarda o primeiro caso de conversão não-BRL para badge
                        if from_ccy and fx_from is None:
                            fx_from = from_ccy
                            fx_rate = rate

                if not brl_vals:
                    continue

                pmin, pmax = min(brl_vals), max(brl_vals)
                pr = PriceResult(
                    query=query,
                    source=self.source_name,
                    title=title[:512],
                    url=url,
                    price_min_brl=round(float(pmin), 2),
                    price_max_brl=round(float(pmax), 2),
                ).clamp()

                # anexa metadados de FX para o app expor no /api/search_live
                if fx_from and fx_rate:
                    # atributo dinâmico, o app checa via hasattr(...)
                    setattr(pr, "_fx_meta", {"from": fx_from, "to": "BRL", "rate": float(fx_rate)})

                results.append(pr)

            if len(results) >= 40:
                break
            time.sleep(0.25)

        time.sleep(0.4)
        return results


# ---------- Diagnóstico ----------
def health_check(test_query: str = "Charizard 4/102") -> Dict[str, Any]:
    """
    Retorna informações úteis para diagnosticar zero-result:
      {
        "env": {"client_id": bool, "client_secret": bool, "marketplace": "EBAY_US"},
        "oauth": {"ok": bool, "last_error": "..."},
        "probe": {"query": "Charizard 4/102", "count": int}
      }
    """
    env = {
        "client_id": bool(os.getenv("EBAY_CLIENT_ID")),
        "client_secret": bool(os.getenv("EBAY_CLIENT_SECRET")),
        "marketplace": os.getenv("EBAY_MP_ID", _DEFAULT_MP).strip().upper() or _DEFAULT_MP,
    }
    tok = _get_oauth_token()
    oauth = {"ok": bool(tok), "last_error": _TokenStore.last_error}

    cnt = 0
    if tok:
        items, _ = _search_once(test_query, tok, env["marketplace"])
        cnt = len(items or [])

    return {
        "env": env,
        "oauth": oauth,
        "probe": {"query": test_query, "count": cnt},
    }
