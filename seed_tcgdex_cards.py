"""seed_tcgdex_cards.py
---------------------------------
Seed de cartas em Português via API TCGdex.

Uso:
    python seed_tcgdex_cards.py                     # importa todos os sets
    python seed_tcgdex_cards.py --sets base1 sv1    # por ID do set
    python seed_tcgdex_cards.py --sets "rivais predestinados"  # por nome
    python seed_tcgdex_cards.py           # importa todos os sets
    python seed_tcgdex_cards.py --sets sv1 sv2  # importa apenas os sets informados
"""

from __future__ import annotations

import argparse
import re
from typing import Iterable, Optional

from app import create_app
from db import db
from scrapers import tcgdex_import


def _slugify(text: str) -> str:
    """Normaliza uma string para comparação simples."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _resolve_sets(identifiers: Iterable[str]) -> list[dict]:
    """Retorna metadados de sets a partir de IDs ou nomes."""
    all_sets = tcgdex_import.get_all_sets()
    name_map = {_slugify(s.get("name", "")): s for s in all_sets if s.get("name")}

    result = []
    for ident in identifiers:
        ident = ident.strip()
        data = tcgdex_import.get_set(ident)
        if data.get("id"):
            result.append(data)
            continue
        # tentativa por nome
        sid = name_map.get(_slugify(ident), {}).get("id")
        if sid:
            result.append(tcgdex_import.get_set(sid))
        else:
            print(f"Set não encontrado: {ident}")
    return result


def _import_sets(set_ids: Optional[Iterable[str]] = None) -> None:
    """Importa sets e cartas usando a API TCGdex."""
    if set_ids:
        sets_data = _resolve_sets(set_ids)
    else:
        # lista básica de sets e busca detalhada de cada um
        sets_list = tcgdex_import.get_all_sets()
        sets_data = [tcgdex_import.get_set(s.get("id")) for s in sets_list if s.get("id")]

    for data in sets_data:
        sid = data.get("id")
        if not sid:
            continue
        set_obj = tcgdex_import.upsert_set(data)
        cards = tcgdex_import.get_cards_from_set(sid, data)
        print(f"[seed_tcgdex_cards] {set_obj.name}: {len(cards)} cartas")
        for card in cards:
            try:
                tcgdex_import.save_card_to_db(card)
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                print(f"Erro ao importar carta {card.get('id')}: {exc}")
        try:
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            print(f"Erro ao commitar set {set_obj.name}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed de cartas via API TCGdex (pt-br).",
    )
    parser.add_argument(
        "--sets",
        nargs="*",
        help="IDs dos sets a importar; se omitido, importa todos",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        _import_sets(args.sets)


if __name__ == "__main__":
    main()
