# scrapers/ptcg_meta.py
"""
Cliente simples da Pokémon TCG API (pokemontcg.io, v2) para metadados de cartas.

Objetivo:
- Normalizar buscas (nome, set, número, raridade, imagens).
- Ajudar a compor títulos canônicos e enriquecer páginas/consultas de preço.

Como usar (exemplo rápido):
    from scrapers.ptcg_meta import PtcgMetaClient
    meta = PtcgMetaClient().search_cards("Charizard 4/102")
    for c in meta:
        print(c.canonical_title)

Requisitos:
- requests + pydantic (já usados no projeto).
- (Opcional) variável de ambiente POKEMONTCG_API_KEY para throughput maior.

Docs: https://docs.pokemontcg.io/
"""
from __future__ import annotations

import os
import re
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from pydantic import BaseModel, Field, HttpUrl

API_BASE = "https://api.pokemontcg.io/v2"
UA = "ptcg-meta-client/1.0 (+pokemon-mvp)"

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


# -------------------- MODELOS --------------------
class CardImages(BaseModel):
    small: Optional[HttpUrl] = None
    large: Optional[HttpUrl] = None


class Prices(BaseModel):
    # placeholders — úteis se você quiser mapear futuramente
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None
    market: Optional[float] = None


class TcgPlayerRef(BaseModel):
    url: Optional[HttpUrl] = None
    updatedAt: Optional[str] = None  # ISO string
    prices: Optional[Dict[str, Prices]] = None  # varia por "variant" (normal, holo, 1stEdition, etc.)


class CardMarketRef(BaseModel):
    url: Optional[HttpUrl] = None
    updatedAt: Optional[str] = None
    prices: Optional[Dict[str, Any]] = None  # schema varia


class SetMeta(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    series: Optional[str] = None
    printedTotal: Optional[int] = None
    total: Optional[int] = None
    ptcgoCode: Optional[str] = Field(default=None, description="Código PTCGO (ex.: 'BS', 'SV1')")
    releaseDate: Optional[str] = None


class CardMeta(BaseModel):
    id: str
    name: str
    supertype: Optional[str] = None
    subtypes: Optional[List[str]] = None
    number: Optional[str] = None
    rarity: Optional[str] = None
    nationalPokedexNumbers: Optional[List[int]] = None

    set: Optional[SetMeta] = None
    images: Optional[CardImages] = None

    tcgplayer: Optional[TcgPlayerRef] = None
    cardmarket: Optional[CardMarketRef] = None

    @property
    def set_code(self) -> Optional[str]:
        # prioriza ptcgoCode; se não houver, usa id do set
        if self.set and self.set.ptcgoCode:
            return self.set.ptcgoCode
        if self.set and self.set.id:
            return self.set.id
        return None

    @property
    def canonical_title(self) -> str:
        """
        Título canônico amigável:
          Nome (SET NÚMERO) [Raridade]
        Ex.: "Charizard (BS 4) [Rare Holo]"
        """
        parts = [self.name]
        code = self.set_code or (self.set.name if self.set else None)
        num = (self.number or "").strip()
        if code and num:
            parts.append(f"({code} {num})")
        elif code:
            parts.append(f"({code})")
        elif num:
            parts.append(f"(#{num})")
        if self.rarity:
            parts.append(f"[{self.rarity}]")
        return " ".join(p for p in parts if p)


# -------------------- UTIL --------------------
@dataclass
class _CacheItem:
    value: Any
    exp_ts: float


class _TTLCache:
    """Cache bem simples com TTL (em segundos)."""

    def __init__(self, ttl_s: float = 180.0, max_items: int = 512):
        self.ttl = float(ttl_s)
        self.max = int(max_items)
        self._store: Dict[str, _CacheItem] = {}

    def get(self, key: str) -> Optional[Any]:
        it = self._store.get(key)
        if not it:
            return None
        if time.time() >= it.exp_ts:
            self._store.pop(key, None)
            return None
        return it.value

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self.max:
            # remove 1º item arbitrariamente (cache simples)
            k = next(iter(self._store.keys()))
            self._store.pop(k, None)
        self._store[key] = _CacheItem(value=value, exp_ts=time.time() + self.ttl)


def _mk_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "application/json",
        }
    )
    api_key = os.getenv("POKEMONTCG_API_KEY")
    if api_key:
        s.headers.update({"X-Api-Key": api_key})
    return s


def _parse_name_number_from_text(text: str) -> Tuple[str, Optional[str]]:
    """
    Tenta separar "nome" e "número" de algo como:
      - "Charizard 4/102"
      - "Charizard #4"
      - "Charizard 4"
    Retorna (name, number) onde number pode ser None.
    """
    s = (text or "").strip()
    if not s:
        return "", None

    # procura padrões 4/102 ou 4-102
    m = re.search(r"(\d+\s*[/\-]\s*\d+)", s)
    if m:
        name = s[: m.start()].strip()
        number = m.group(1).replace(" ", "")
        number = number.split("/")[0].split("-")[0]  # fica só o primeiro número
        return name, number

    # padrão #4 ou Nº 4
    m2 = re.search(r"(#|nº|no\.?)\s*(\d+)", s, flags=re.IGNORECASE)
    if m2:
        name = s[: m2.start()].strip()
        number = m2.group(2)
        return name, number

    # por fim, se terminar com número solto
    m3 = re.search(r"(\d+)\s*$", s)
    if m3:
        name = s[: m3.start()].strip()
        number = m3.group(1)
        return name, number

    return s, None


def _as_str(u: Optional[HttpUrl]) -> Optional[str]:
    """Converte HttpUrl/AnyUrl em str para ser JSON-serializable."""
    if not u:
        return None
    try:
        return str(u)
    except Exception:
        return None


# -------------------- CLIENTE --------------------
class PtcgMetaClient:
    """
    Cliente enxuto para a Pokémon TCG API v2.
    - search_cards("Charizard 4/102") → lista de CardMeta
    - by_set_and_number("BS", "4") ou by_set_and_number("base1", "4") → lista (em geral 1)
    - normalize_query("Charizard 4/102") → tenta produzir padrões melhores de busca
    """

    def __init__(self, base_url: str = API_BASE, delay_s: float = 0.25, cache_ttl_s: float = 240):
        self.base = base_url.rstrip("/")
        self.delay = float(delay_s)
        self.cache = _TTLCache(ttl_s=cache_ttl_s)
        self.s = _mk_session()

    # ---------- HTTP ----------
    def _get(self, path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = f"{self.base}/{path.lstrip('/')}"
        key = f"GET|{url}|{sorted(params.items())}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            r = self.s.get(url, params=params, timeout=20)
            r.raise_for_status()
            j = r.json()
            self.cache.set(key, j)
            time.sleep(self.delay)  # respeita limites
            return j
        except Exception as e:
            log.warning("ptcg_meta GET error: %s", e)
            return None

    # ---------- HELPERS ----------
    @staticmethod
    def normalize_query(raw: str) -> Dict[str, Any]:
        """
        Retorna dict com campos úteis para montar uma consulta bacana:
          {
            "name": "Charizard",
            "number": "4",
            "q_exact": 'name:"Charizard" number:4',
            "q_loose": 'name:*Charizard*',
          }
        """
        name, number = _parse_name_number_from_text(raw)
        name_q = re.sub(r"\s+", " ", (name or "")).strip()
        q_exact_parts = []
        if name_q:
            q_exact_parts.append(f'name:"{name_q}"')
        if number:
            q_exact_parts.append(f"number:{number}")
        q_exact = " ".join(q_exact_parts) if q_exact_parts else None
        q_loose = f'name:*{name_q}*' if name_q else None
        return {"name": name_q, "number": number, "q_exact": q_exact, "q_loose": q_loose}

    # ---------- BUSCAS ----------
    def search_cards(self, text: str, page_size: int = 50, page: int = 1) -> List[CardMeta]:
        """
        Busca por texto livre (name/number) usando heurística:
          1) tentativa mais estrita (q_exact)
          2) fallback para fuzzy (q_loose)
        """
        norm = self.normalize_query(text)
        for q in (norm.get("q_exact"), norm.get("q_loose")):
            if not q:
                continue
            params = {"q": q, "page": page, "pageSize": max(1, min(250, int(page_size)))}
            data = self._get("cards", params=params)
            if not data or not isinstance(data.get("data"), list):
                continue
            cards = [CardMeta(**c) for c in data["data"] if isinstance(c, dict)]
            if cards:
                return cards
        return []

    def by_set_and_number(self, set_code_or_id: str, number: str) -> List[CardMeta]:
        """
        Tenta localizar carta por set e número.
        set_code_or_id pode ser:
          - set.id (ex.: 'base1', 'sv1')
          - set.ptcgoCode (ex.: 'BS', 'SV1')
        """
        set_term = set_code_or_id.strip()
        number = str(number).strip()

        attempts = [
            f"set.ptcgoCode:{set_term} number:{number}",
            f"set.id:{set_term} number:{number}",
            f'name:*{set_term}* number:{number}',  # fallback amplo
        ]
        for q in attempts:
            data = self._get("cards", params={"q": q, "pageSize": 20})
            if not data or not isinstance(data.get("data"), list):
                continue
            cards = [CardMeta(**c) for c in data["data"] if isinstance(c, dict)]
            if cards:
                return cards
        return []

    # ---------- CONVENIÊNCIAS ----------
    @staticmethod
    def best_image(meta: CardMeta) -> Optional[str]:
        if meta.images and meta.images.large:
            return str(meta.images.large)
        if meta.images and meta.images.small:
            return str(meta.images.small)
        return None

    @staticmethod
    def to_display_row(meta: CardMeta) -> Dict[str, Any]:
        """
        Linha genérica para mostrar em tabelas/listas no frontend.
        Garante que URLs sejam strings JSON-serializáveis.
        """
        tcg_url = _as_str(meta.tcgplayer.url) if meta.tcgplayer else None
        cdm_url = _as_str(meta.cardmarket.url) if meta.cardmarket else None

        return {
            "id": meta.id,
            "title": meta.canonical_title,
            "name": meta.name,
            "set": (meta.set.name if meta.set else None),
            "set_code": meta.set_code,
            "number": meta.number,
            "rarity": meta.rarity,
            "image": PtcgMetaClient.best_image(meta),
            "tcgplayer_url": tcg_url,
            "cardmarket_url": cdm_url,
        }
