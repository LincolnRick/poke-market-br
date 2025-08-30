from __future__ import annotations

import re
import unicodedata
from typing import List, Optional

from db import db, Card, CardSearchToken

_NUMBER_RE = re.compile(r"^\s*\d+(?:\s*/\s*\d+)?\s*$")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _tokenize(text: str) -> List[str]:
    raw = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text or "")
    return [_strip_accents(t).lower() for t in raw if t]


def update_card_search_tokens(card: Card) -> None:
    tokens = set(
        _tokenize(card.name or "")
        + _tokenize(card.name_pt or "")
        + _tokenize(card.number or "")
    )
    card.search_tokens.clear()
    for tok in tokens:
        card.search_tokens.append(CardSearchToken(token=tok[:50]))
    db.session.flush()


def ensure_card_tokens() -> None:
    cards = Card.query.all()
    changed = False
    for c in cards:
        if not c.search_tokens:
            update_card_search_tokens(c)
            changed = True
    if changed:
        db.session.commit()


def search_cards(q: str, *, set_id: Optional[str] = None, rarity: Optional[str] = None) -> List[Card]:
    query = Card.query
    q = (q or "").strip()
    if q:
        if _NUMBER_RE.match(q):
            number = re.sub(r"\s*/\s*", "/", q)
            query = query.filter(
                Card.number == (number.split("/")[0] if "/" in number else number)
            )
        else:
            for tok in _tokenize(q):
                query = query.filter(
                    Card.search_tokens.any(CardSearchToken.token.like(f"{tok}%"))
                )
    if set_id:
        try:
            query = query.filter(Card.set_id == int(set_id))
        except ValueError:
            pass
    if rarity:
        query = query.filter(Card.rarity == rarity)
    return query.order_by(Card.name_pt.asc(), Card.name.asc()).limit(200).all()
