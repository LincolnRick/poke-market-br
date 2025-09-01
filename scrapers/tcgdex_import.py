"""scrapers/tcgdex_import.py
-------------------------------
Importador de cartas usando a API TCGdex (pt-br).
Armazena dados básicos das cartas em um SQLite local.
"""

from __future__ import annotations

from datetime import date
from time import sleep
from typing import Any, Dict, List, Optional

import requests

from db import db, Set, Card, PriceHistory


API_SETS = "https://api.tcgdex.net/v2/pt-br/sets"
API_CARDS = "https://api.tcgdex.net/v2/pt-br/cards"


def get_all_sets() -> List[Dict[str, Any]]:
    """Obtém todos os conjuntos disponíveis em pt-br."""
    try:
        resp = requests.get(API_SETS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao obter conjuntos: {exc}")
        return []


def get_set(set_id: str) -> Dict[str, Any]:
    """Obtém informações detalhadas de um set específico."""
    url = f"{API_SETS}/{set_id}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao obter set {set_id}: {exc}")
        return {}


def fetch_card_detail(card_id: str) -> Dict[str, Any]:
    """Obtém detalhes completos de uma carta específica com retry simples."""
    url = f"{API_CARDS}/{card_id}"
    backoff = 1.0
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            print(
                f"Erro ao obter carta {card_id} (tentativa {attempt + 1}/3): {exc}"
            )
            sleep(backoff)
            backoff *= 2
    return {}


def get_cards_from_set(set_id: str, set_data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Obtém e enriquece as cartas pertencentes a um conjunto específico."""
    data = set_data or get_set(set_id)
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, list):
        return []

    enriched: List[Dict[str, Any]] = []
    for card in cards:
        cid = card.get("id")
        detail = fetch_card_detail(cid) if cid else {}
        merged = {**card, **detail} if detail else card
        enriched.append(merged)
    return enriched


def _find_or_create_set(set_data: Dict[str, Any]) -> Set:
    """Localiza ou cria um Set usando código ou nome."""
    code = set_data.get("id") or set_data.get("code")
    name = set_data.get("name")

    set_obj: Set | None = None
    if code:
        set_obj = Set.query.filter_by(code=code).first()
    if set_obj is None and name:
        set_obj = Set.query.filter_by(name=name).first()

    if set_obj is None:
        release_date = date.today()
        if set_data.get("releaseDate"):
            try:
                release_date = date.fromisoformat(set_data["releaseDate"])
            except ValueError:
                pass
        images = set_data.get("images") or {}
        icon_url = images.get("symbol") or images.get("logo")

        set_obj = Set(code=code, name=name, release_date=release_date, icon_url=icon_url)
        db.session.add(set_obj)
        db.session.flush()
    return set_obj


def upsert_set(tcgdex_set: Dict[str, Any]) -> Set:
    """Upsert de um Set baseado no JSON retornado pela API."""
    code = tcgdex_set.get("id")
    name = tcgdex_set.get("name")

    set_obj: Set | None = None
    if code:
        set_obj = Set.query.filter_by(code=code).first()
    if set_obj is None and name:
        set_obj = Set.query.filter_by(name=name).first()

    if set_obj is None:
        set_obj = Set(code=code, name=name or "")
        db.session.add(set_obj)

    if name:
        set_obj.name = name
    if code:
        set_obj.code = code

    release_date = tcgdex_set.get("releaseDate")
    if release_date:
        try:
            set_obj.release_date = date.fromisoformat(release_date)
        except ValueError:
            pass

    images = tcgdex_set.get("images") or {}
    icon_url = images.get("symbol") or images.get("logo")
    if icon_url:
        set_obj.icon_url = icon_url

    db.session.flush()
    return set_obj


def save_card_to_db(card_data: Dict[str, Any]) -> None:
    """Upsert da carta usando (set_id, localId)."""
    set_info = card_data.get("set") or {}
    set_obj = _find_or_create_set(set_info)

    number = card_data.get("localId")
    if not number:
        return

    card = Card.query.filter_by(set_id=set_obj.id, number=number).first()
    if card is None:
        card = Card(set_id=set_obj.id, number=number)
        db.session.add(card)

    card.name = card_data.get("name")
    card.rarity = card_data.get("rarity")
    types = card_data.get("types")
    if isinstance(types, list) and types:
        card.type = types[0]
    else:
        card.type = None
    card.image_url = (
        card_data.get("image")
        or (card_data.get("images") or {}).get("large")
        or (card_data.get("images") or {}).get("small")
    )

    prices = card_data.get("prices")
    price_value = _extract_price(prices)
    if price_value is not None:
        db.session.flush()
        db.session.add(
            PriceHistory(card_id=card.id, price=float(price_value), source="tcgdex")
        )


def _extract_price(data: Any) -> Optional[float]:
    """Extrai o primeiro valor numérico encontrado em uma estrutura de preços."""
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, dict):
        for val in data.values():
            price = _extract_price(val)
            if price is not None:
                return price
    if isinstance(data, list):
        for val in data:
            price = _extract_price(val)
            if price is not None:
                return price
    return None


def main() -> None:
    """Fluxo principal: importa todas as cartas da API."""
    from app import create_app

    app = create_app()
    with app.app_context():
        sets = get_all_sets()
        for s in sets:
            sid = s.get("id")
            if not sid:
                continue
            set_data = get_set(sid)
            set_obj = upsert_set(set_data)
            cards = get_cards_from_set(sid, set_data)
            print(f"Processando conjunto {set_obj.name} – {len(cards)} cartas")
            for card in cards:
                try:
                    save_card_to_db(card)
                except Exception as exc:  # noqa: BLE001
                    db.session.rollback()
                    print(f"Erro ao processar carta {card.get('id')}: {exc}")
            try:
                db.session.commit()
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                print(f"Erro ao commitar set {set_obj.name}: {exc}")


if __name__ == "__main__":
    main()
