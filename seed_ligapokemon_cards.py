"""seed_ligapokemon_cards.py
---------------------------------
Script de seeding que importa cartas diretamente do site Liga Pokémon.

Uso:
    python seed_ligapokemon_cards.py --edids 706 707

Para cada `edid` informado, o script busca todas as cartas do set
correspondente via :func:`scrapers.ligapokemon_cards.fetch_set_cards`
e realiza *upsert* em :class:`db.Set` e :class:`db.Card`.

É idempotente graças à constraint de unicidade ``(set_id, number)`` já
existente em ``db.Card``.
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any, Dict

from app import create_app
from db import db, Set, Card
from scrapers.ligapokemon_cards import fetch_set_cards


def _extract_set_name(card: Dict[str, Any]) -> str | None:
    """Tenta identificar o nome do set nos dados de uma carta."""
    for key in ("expansao", "edicao", "set", "edition", "set_name"):
        val = card.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def process_edid(edid: str, delay_s: float = 0.8) -> None:
    cards = fetch_set_cards(edid, delay_s=delay_s)
    if not cards:
        print(f"[seed_ligapokemon_cards] edid {edid}: nenhuma carta encontrada.")
        return

    set_name = _extract_set_name(cards[0]) or f"LigaPokemon {edid}"
    set_code = f"lp-{edid}"

    set_obj = Set.query.filter((Set.code == set_code) | (Set.name == set_name)).first()
    if set_obj is None:
        set_obj = Set(name=set_name, code=set_code, release_date=date.today())
        db.session.add(set_obj)
        db.session.flush()

    inserted = updated = 0
    for data in cards:
        name = data.get("name") or data.get("nome")
        number = data.get("number") or data.get("numero")
        if not name:
            continue

        card = Card.query.filter_by(set_id=set_obj.id, number=number).first()
        if card is None:
            card = Card(set_id=set_obj.id, number=number, name=name)
            db.session.add(card)
            inserted += 1
        else:
            updated += 1

        mapping = {
            "rarity": ("rarity", "raridade"),
            "type": ("type", "tipo"),
            "image_url": ("image", "image_url", "imagem"),
            "hp": ("hp",),
            "category": ("categoria", "category"),
            "language": ("language", "idioma"),
            "border": ("border", "borda"),
            "holo": ("holo",),
            "material": ("material",),
            "edition": ("edition", "edicao"),
        }
        for attr, keys in mapping.items():
            for k in keys:
                v = data.get(k)
                if v:
                    setattr(card, attr, v)
                    break

        if not getattr(card, "language", None):
            card.language = "português"

    set_obj.total_cards = len(cards)
    db.session.commit()
    print(
        f"[seed_ligapokemon_cards] {set_obj.name}: {len(cards)} cartas (ins {inserted}, upd {updated})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed de cartas via Liga Pokémon (scraper)."
    )
    parser.add_argument(
        "--edids",
        nargs="+",
        required=True,
        help="Lista de edids (edições) da Liga Pokémon",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="Pausa entre requisições de detalhes (segundos)",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        for edid in args.edids:
            process_edid(str(edid), delay_s=args.delay)


if __name__ == "__main__":
    main()
