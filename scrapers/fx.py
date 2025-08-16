# scrapers/fx.py
"""
Conversor FX simples com cache em memória.
Objetivo: converter USD/EUR/etc. -> BRL para normalizar preços (ex.: eBay).

- Usa https://api.exchangerate.host/ (gratuito) como provedor padrão.
- Cache por 6 horas por par de moedas.
- Fallback: tenta um segundo provedor se o primeiro falhar.
- Permite override de taxa via variável de ambiente, ex.:
    FX_OVERRIDE_USD_BRL=5.25
    FX_OVERRIDE_EUR_BRL=6.10

Uso:
    from scrapers.fx import convert
    brl = convert(10, "USD", "BRL")  # -> 10 USD em BRL (float) ou None
"""

from __future__ import annotations

import os
import time
from typing import Optional, Tuple, Dict

import requests

# -------- Config --------
CACHE_TTL_S = float(os.getenv("FX_CACHE_TTL_S", "21600"))  # default 6h
TIMEOUT = float(os.getenv("FX_TIMEOUT_S", "8"))

UA = "poke-market-br/1.0 (+fx)"

HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
}

# cache em memória: {("USD","BRL"): (rate, exp_ts)}
_cache: Dict[Tuple[str, str], Tuple[float, float]] = {}


def _override_rate(base: str, quote: str) -> Optional[float]:
    """
    Permite fixar taxa via env var, ex.: FX_OVERRIDE_USD_BRL=5.25
    """
    key = f"FX_OVERRIDE_{base.upper()}_{quote.upper()}"
    v = os.getenv(key)
    if not v:
        return None
    try:
        r = float(v)
        return r if r > 0 else None
    except Exception:
        return None


def _get_cached(base: str, quote: str) -> Optional[float]:
    k = (base.upper(), quote.upper())
    it = _cache.get(k)
    if not it:
        return None
    rate, exp = it
    if time.time() >= exp:
        _cache.pop(k, None)
        return None
    return rate


def _set_cached(base: str, quote: str, rate: float) -> None:
    k = (base.upper(), quote.upper())
    _cache[k] = (float(rate), time.time() + CACHE_TTL_S)


def _fetch_rate_exchangerate_host(base: str, quote: str) -> Optional[float]:
    """
    https://api.exchangerate.host/latest?base=USD&symbols=BRL
    """
    url = "https://api.exchangerate.host/latest"
    try:
        r = requests.get(url, headers=HEADERS, params={"base": base, "symbols": quote}, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        rates = j.get("rates") or {}
        val = rates.get(quote.upper())
        if val and float(val) > 0:
            return float(val)
    except Exception:
        return None
    return None


def _fetch_rate_erapi(base: str, quote: str) -> Optional[float]:
    """
    Fallback: https://open.er-api.com/v6/latest/USD
    """
    url = f"https://open.er-api.com/v6/latest/{base.upper()}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        rates = j.get("rates") or {}
        val = rates.get(quote.upper())
        if val and float(val) > 0:
            return float(val)
    except Exception:
        return None
    return None


def get_rate(base: str, quote: str = "BRL") -> Optional[float]:
    """
    Retorna taxa base→quote (ex.: USD→BRL) ou None se indisponível.
    Ordem:
      1) override por env
      2) cache
      3) provedor 1
      4) provedor 2 (fallback)
    """
    base = base.upper().strip()
    quote = quote.upper().strip()

    if base == quote:
        return 1.0

    ov = _override_rate(base, quote)
    if ov:
        return ov

    cached = _get_cached(base, quote)
    if cached:
        return cached

    for fn in (_fetch_rate_exchangerate_host, _fetch_rate_erapi):
        rate = fn(base, quote)
        if rate and rate > 0:
            _set_cached(base, quote, rate)
            return rate
    return None


def convert(amount: float, from_ccy: str, to_ccy: str = "BRL") -> Optional[float]:
    """
    Converte amount de from_ccy para to_ccy (float arredondado a 4 casas).
    """
    try:
        amt = float(amount)
    except Exception:
        return None
    if amt <= 0:
        return None

    from_ccy = from_ccy.upper().strip()
    to_ccy = to_ccy.upper().strip()
    if from_ccy == to_ccy:
        return round(amt, 4)

    rate = get_rate(from_ccy, to_ccy)
    if not rate:
        return None
    return round(amt * rate, 4)
