"""scrapers/tcgdex_import.py
-------------------------------
Importador de cartas usando a API TCGdex (pt-br).
Armazena dados básicos das cartas em um SQLite local.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import requests

from db import db, Set, Card


API_SETS = "https://api.tcgdex.net/v2/pt-br/sets"


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


def get_cards_from_set(set_id: str) -> List[Dict[str, Any]]:
    """Obtém as cartas pertencentes a um conjunto específico."""
    url = f"{API_SETS}/{set_id}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        cards = data.get("cards")
        return cards if isinstance(cards, list) else []
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao obter cartas do set {set_id}: {exc}")
        return []


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
    card.type = (card_data.get("types") or [None])[0]
    card.image_url = (
        card_data.get("image")
        or (card_data.get("images") or {}).get("large")
        or (card_data.get("images") or {}).get("small")
    )


def main() -> None:
    """Fluxo principal: importa todas as cartas da API."""
    from app import create_app

    app = create_app()
    with app.app_context():
        sets = get_all_sets()
        for s in sets:
            sid = s.get("id")
            nome = s.get("name")
            if not sid:
                continue
            cards = get_cards_from_set(sid)
            print(f"Processando conjunto {nome} – {len(cards)} cartas")
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
                print(f"Erro ao commitar set {nome}: {exc}")


if __name__ == "__main__":
    main()
