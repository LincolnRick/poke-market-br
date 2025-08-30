from __future__ import annotations

import os
from datetime import datetime
from typing import Optional, Dict, List

import requests

from db import db, Set, Card
from services.search import update_card_search_tokens

API_BASE = "https://api.tcgdex.net/v2/pt-br"
HTTP_TIMEOUT = 15

_SESSION: Optional[requests.Session] = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    s = requests.Session()
    s.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "poke-market/0.1 (+tcgdex)"
        }
    )
    _SESSION = s
    return s


def _get_json(url: str) -> Optional[Dict]:
    try:
        r = _session().get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _parse_date(s: Optional[str]):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def upsert_set(api_set: Dict) -> Set:
    code = api_set.get("id") or api_set.get("code")
    name = api_set.get("name")
    if not code or not name:
        raise ValueError("set sem id/nome")
    icon_url = (api_set.get("images") or {}).get("logo")
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


def upsert_card(api_card: Dict, s: Set) -> Card:
    name = api_card.get("name") or "?"
    number = api_card.get("number")
    rarity = api_card.get("rarity")
    types = api_card.get("types") or []
    ctype = types[0] if types else None
    images = api_card.get("images") or {}
    image_url = images.get("large") or images.get("small")
    c = Card.query.filter_by(set_id=s.id, number=number).first()
    if not c:
        c = Card(set_id=s.id, name=name, number=number, rarity=rarity, type=ctype, image_url=image_url)
        db.session.add(c)
    else:
        c.name = name
        c.rarity = rarity
        c.type = ctype
        c.image_url = image_url
    db.session.flush()
    update_card_search_tokens(c)
    return c


def import_set(set_code: str) -> Optional[Set]:
    api_set = _get_json(f"{API_BASE}/sets/{set_code}")
    if not api_set:
        return None
    s = upsert_set(api_set)
    db.session.commit()
    return s


def import_by_print_number(number: str, set_code: Optional[str] = None) -> List[Card]:
    if not set_code:
        return []
    api_card = _get_json(f"{API_BASE}/cards/{set_code}/{number.split('/')[0]}")
    if not api_card:
        return []
    s = import_set(set_code)
    if not s:
        return []
    card = upsert_card(api_card, s)
    db.session.commit()
    return [card]


def ensure_single_by_number(number: str) -> Optional[Card]:
    number = number.split('/')[0]
    cards = Card.query.filter(Card.number == number).all()
    if len(cards) == 1:
        return cards[0]
    return None
