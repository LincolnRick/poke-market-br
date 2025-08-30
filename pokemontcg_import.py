# pokemontcg_import.py
# -----------------------------------------------------------------------------
# Importador oficial de cartas usando Pokémon TCG API v2
# - Importa por número impresso "X/Y" (ex.: 178/132) e por "X"
# - Importa por NOME (ex.: "Psyduck", "Charizard", "Gardevoir ex")
# - Usa set.printedTotal e set.total quando Y é informado (cobre Secret Rares X>Y)
# - Aceita set_code (id do set v2: "sm9", "sv6", "base1") para afunilar a busca
# - Timeouts maiores + retries com backoff para evitar falhas por rede
# - Upsert de Set e Card no nosso banco
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry  # type: ignore
except Exception:
    Retry = None  # type: ignore

from db import db, Set, Card
from scrapers.ligapokemon_html import LigaPokemonHTMLScraper
from liga_market import _build_queries as _br_queries
from services.search import update_card_search_tokens

API_BASE = "https://api.pokemontcg.io/v2"
CARDS_EP = f"{API_BASE}/cards"
SETS_EP  = f"{API_BASE}/sets"

HTTP_TIMEOUT = 15  # segundos
PAGE_SIZE = 50     # evita payloads gigantes

# ========= Sessão HTTP com retries =========
_SESSION: Optional[requests.Session] = None
_PT_SCRAPER = LigaPokemonHTMLScraper()

def _session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION

    s = requests.Session()
    headers = {
        "Accept": "application/json",
        "User-Agent": "collectr-importer/1.3 (+pokemontcg_v2)",
    }
    api_key = os.getenv("POKEMONTCG_API_KEY") or os.getenv("POKEMON_TCG_API_KEY")
    if api_key:
        headers["X-Api-Key"] = api_key
    s.headers.update(headers)

    if Retry:
        r = Retry(
            total=4, connect=4, read=4,
            backoff_factor=0.8,
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        ad = HTTPAdapter(max_retries=r, pool_connections=10, pool_maxsize=12)
        s.mount("https://", ad); s.mount("http://", ad)
    _SESSION = s
    return s

def _get_json(url: str, params: Dict) -> Optional[Dict]:
    try:
        r = _session().get(url, params=params, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

# ========= Parse número impresso =========
NUM_SLASH = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")

def parse_print_number(raw: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Retorna (X, Y) a partir de "X/Y" ou (X, None) a partir de "X".
    """
    if not raw:
        return None, None
    txt = str(raw).strip()
    m = NUM_SLASH.match(txt)
    if m:
        try:
            return int(m.group(1)), int(m.group(2))
        except Exception:
            return None, None
    try:
        return int(txt), None
    except Exception:
        return None, None

# ========= Upserts =========
def _parse_date(s: Optional[str]) -> Optional[datetime.date]:
    if not s:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def upsert_set(api_set: Dict) -> Set:
    """Cria/atualiza um Set local a partir do JSON v2."""
    sid = api_set.get("id")
    name = api_set.get("name")
    if not sid or not name:
        raise ValueError("set sem id/nome")

    code = sid  # usamos o id oficial v2 como 'code' local
    icon_url = (api_set.get("images") or {}).get("logo") or None
    release_date = _parse_date(api_set.get("releaseDate"))

    s = Set.query.filter_by(code=code).first()
    if not s:
        s = Set(code=code, name=name, icon_url=icon_url, release_date=release_date)
        db.session.add(s)
    else:
        s.name = name
        s.icon_url = icon_url
        s.release_date = release_date
    db.session.flush()
    return s

def _enrich_portuguese(card: Card) -> None:
    """Preenche nome e imagem em PT-BR usando Liga Pokémon."""
    if card.name_pt and card.image_url_pt:
        return
    queries = _br_queries(card)
    for q in queries:
        try:
            results = _PT_SCRAPER.search(q)
        except Exception:
            continue
        if not results:
            continue
        best = results[0]
        card.name_pt = best.title[:200]
        if best.image_url:
            card.image_url_pt = best.image_url[:500]
        break

def upsert_card(api_card: Dict, s: Set) -> Card:
    """Cria/atualiza um Card local no Set informado."""
    name = api_card.get("name") or "?"
    number = api_card.get("number") or None  # string "178"
    rarity = api_card.get("rarity") or None
    types = api_card.get("types") or []
    supertype = api_card.get("supertype") or None
    ctype = (types[0] if types else (supertype or None))
    images = api_card.get("images") or {}
    image_url = images.get("large") or images.get("small") or None

    c = Card.query.filter_by(set_id=s.id, number=number).first()
    if not c:
        c = Card(set_id=s.id, name=name, number=number, rarity=rarity, type=ctype, image_url=image_url)
        db.session.add(c)
    else:
        c.name = name
        c.rarity = rarity
        c.type = ctype
        c.image_url = image_url
    try:
        _enrich_portuguese(c)
    except Exception:
        pass
    db.session.flush()
    update_card_search_tokens(c)
    return c

# ========= Buscar set por código =========
def fetch_set_by_code(set_code: str) -> Optional[Dict]:
    """
    Tenta achar o set por id exato (v2: set.id), depois por ptcgoCode e por nome.
    """
    # 1) id exato
    data = _get_json(SETS_EP, params={"q": f'id:"{set_code}"'})
    if data and data.get("data"):
        return data["data"][0]
    # 2) ptcgoCode
    data = _get_json(SETS_EP, params={"q": f'ptcgoCode:"{set_code}"'})
    if data and data.get("data"):
        return data["data"][0]
    # 3) nome
    data = _get_json(SETS_EP, params={"q": f'name:"{set_code}"'})
    if data and data.get("data"):
        return data["data"][0]
    return None

def import_set(set_code: str) -> Optional[Set]:
    api_set = fetch_set_by_code(set_code)
    if not api_set:
        return None
    s = upsert_set(api_set)
    db.session.commit()
    return s

# ========= Montar consultas de carta =========
def _card_query_variants_number(x: Optional[int], y: Optional[int], set_code: Optional[str]) -> List[str]:
    queries: List[str] = []

    set_filters: List[str] = []
    if set_code:
        set_filters.append(f'set.id:"{set_code}"')

    if x is not None and y is not None:
        base_xy = [
            f'number:"{x}" set.printedTotal:{y}',
            f'number:{x} set.printedTotal:{y}',
            f'number:"{x}" set.total:{y}',
            f'number:{x} set.total:{y}',
        ]
        # Secret rares (X>Y)
        if x > y:
            base_xy += [
                f'number:{x} set.printedTotal:{y} rarity:"Rare Secret"',
                f'number:{x} set.total:{y} rarity:"Rare Secret"',
                f'number:{x} set.printedTotal:{y} rarity:"Secret Rare"',
                f'number:{x} set.total:{y} rarity:"Secret Rare"',
            ]
        if set_filters:
            for bf in base_xy:
                for sf in set_filters:
                    queries.append(f"{bf} {sf}")
        queries += base_xy

    if x is not None:
        base_x = [
            f'number:"{x}"',
            f'number:{x}',
        ]
        if set_filters:
            for bf in base_x:
                for sf in set_filters:
                    queries.append(f"{bf} {sf}")
        queries += base_x

    # Dedup mantendo ordem
    seen = set()
    uniq = []
    for q in queries:
        if q not in seen:
            uniq.append(q); seen.add(q)
    return uniq[:24] if uniq else ['name:"*"']

def _card_query_variants_name(qtext: str, set_code: Optional[str]) -> List[str]:
    """
    Monta consultas por nome com diferentes variantes que a API costuma entender.
    """
    qtext = qtext.strip()
    # Variantes: aspas exatas e sem aspas (fuzzy)
    bases = [
        f'name:"{qtext}"',
        f'name:{qtext}',
    ]
    # Alguns sufixos comuns ("ex", "V", "VMAX") já funcionam via name:...
    # Filtros de set (quando informados)
    queries: List[str] = []
    if set_code:
        for b in bases:
            queries.append(f'{b} set.id:"{set_code}"')
    queries += bases

    # Dedup
    seen = set(); uniq = []
    for q in queries:
        if q not in seen:
            uniq.append(q); seen.add(q)
    return uniq[:12]

def _fetch_cards(q: str) -> List[Dict]:
    data = _get_json(CARDS_EP, params={"q": q, "pageSize": PAGE_SIZE})
    if not data or "data" not in data:
        return []
    arr = data["data"]
    return arr if isinstance(arr, list) else []

def _match_print(card: Dict, x: Optional[int], y: Optional[int]) -> bool:
    """Confirma se a carta bate com X/Y (quando fornecidos)."""
    try:
        cnum = int(str(card.get("number","")).strip())
    except Exception:
        return False if x is not None else True

    if x is None and y is None:
        return True
    if x is not None and cnum != x:
        return False
    if y is not None:
        set_obj = card.get("set") or {}
        printed_total = set_obj.get("printedTotal")
        total = set_obj.get("total")
        # aceita printedTotal OU total igual a Y
        if printed_total is None and total is None:
            return True
        if printed_total is not None and int(printed_total) == y:
            return True
        if total is not None and int(total) == y:
            return True
        return False
    return True

def _ensure_local_set(set_json: Dict) -> Set:
    sid = set_json.get("id")
    if not sid:
        raise ValueError("card.set sem id")
    s = Set.query.filter_by(code=sid).first()
    if s:
        s.name = set_json.get("name") or s.name
        s.icon_url = ((set_json.get("images") or {}).get("logo")) or s.icon_url
        s.release_date = _parse_date(set_json.get("releaseDate")) or s.release_date
        db.session.flush()
        return s
    return upsert_set(set_json)

# ========= Públicos =========
def import_by_print_number(number: str, set_code: Optional[str] = None) -> List[Card]:
    """
    Importa e devolve as cartas que batem com o número impresso.
    - number: "X/Y" ou "X"
    - set_code (opcional): id do set (ex.: "sm9", "sv6", "base1")
    """
    x, y = parse_print_number(number)
    if x is None and y is None:
        return []

    # Se set_code veio, garanta o Set local (ajuda a filtrar)
    if set_code:
        if not Set.query.filter_by(code=set_code).first():
            import_set(set_code)

    queries = _card_query_variants_number(x, y, set_code)

    imported: List[Card] = []
    seen_keys = set()

    for q in queries:
        cards = _fetch_cards(q)
        if not cards:
            time.sleep(0.12)
            continue

        filtered = [c for c in cards if _match_print(c, x, y)]
        if not filtered:
            time.sleep(0.08)
            continue

        for jc in filtered:
            set_json = jc.get("set") or {}
            if not set_json:
                continue
            s = _ensure_local_set(set_json)
            c = upsert_card(jc, s)
            key = (c.set_id, c.number)
            if key not in seen_keys:
                imported.append(c)
                seen_keys.add(key)

        # Se estamos buscando X/Y e já importamos algo compatível, podemos parar
        if imported and y is not None:
            break

        time.sleep(0.08)

    db.session.commit()
    return imported

def ensure_single_by_number(number: str) -> Optional[Card]:
    """
    Garante que exista UMA única carta local para o número informado.
    - Tenta importar automaticamente (sem set_code).
    - Se, após import, houver exatamente 1 Card com numerador X, retorna-o.
    """
    x, y = parse_print_number(number)
    if x is None and y is None:
        return None

    import_by_print_number(number)

    q = Card.query.filter(Card.number == str(x))
    found = q.all()
    if len(found) == 1:
        return found[0]
    return None

def import_by_name(name_query: str, set_code: Optional[str] = None, limit: int = 60) -> List[Card]:
    """
    Importa cartas pelo NOME (case-insensitive) e retorna as inseridas/atualizadas.
    - name_query: ex.: "Psyduck", "Gardevoir ex"
    - set_code: restringe ao set (id v2, ex.: "sm9")
    - limit: máximo de cartas a trazer (cap de segurança)
    """
    name_query = (name_query or "").strip()
    if not name_query:
        return []

    # Se a pessoa digitou "X/Y", delega para import_by_print_number
    if NUM_SLASH.match(name_query) or name_query.isdigit():
        return import_by_print_number(name_query, set_code=set_code)

    # Se set_code veio, garante o Set local
    if set_code:
        if not Set.query.filter_by(code=set_code).first():
            import_set(set_code)

    queries = _card_query_variants_name(name_query, set_code)
    imported: List[Card] = []
    seen_keys = set()

    for q in queries:
        cards = _fetch_cards(q)
        if not cards:
            time.sleep(0.10)
            continue

        for jc in cards:
            set_json = jc.get("set") or {}
            if not set_json:
                continue
            s = _ensure_local_set(set_json)
            c = upsert_card(jc, s)
            key = (c.set_id, c.number)
            if key not in seen_keys:
                imported.append(c)
                seen_keys.add(key)
                if len(imported) >= limit:
                    break
        if len(imported) >= limit:
            break
        time.sleep(0.08)

    db.session.commit()
    return imported

# Conveniência: busca híbrida (tenta número, depois nome)
def import_hybrid(query: str, set_code: Optional[str] = None, limit: int = 60) -> List[Card]:
    """
    Import híbrido: se for X/Y ou X → número; senão, por nome.
    Retorna lista de Cards importados/atualizados no banco local.
    """
    query = (query or "").strip()
    if not query:
        return []
    if NUM_SLASH.match(query) or query.isdigit():
        return import_by_print_number(query, set_code=set_code)
    return import_by_name(query, set_code=set_code, limit=limit)
