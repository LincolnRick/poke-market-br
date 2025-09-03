from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import sys

import typer
from tqdm import tqdm

# add project root to path so that app and other modules can be imported when
# executing the script directly
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app import create_app
from db import Set, db
from scrapers.tcgdex_import import save_card_to_db, upsert_set
from lib.tcgdex_parser import parse_data


app = typer.Typer(help="Importa dados do repositório tcgdex/cards-database")


def _resolve_name(raw: Any, lang: str) -> str:
    if isinstance(raw, dict):
        return raw.get(lang) or raw.get("en") or next(iter(raw.values()), "")
    return str(raw)


@app.command()
def main(
    repo_path: Path = typer.Option(..., help="Diretório do cards-database"),
    lang: str = typer.Option("en", help="Idioma principal"),
    full_refresh: bool = typer.Option(
        False, help="Remove o set existente antes de importar"
    ),
) -> None:
    """Carrega cartas do diretório ``cards-database`` para o banco."""

    flask_app = create_app()
    with flask_app.app_context():
        current_set: str | None = None
        for card in tqdm(parse_data(repo_path, lang), unit="card"):
            set_info: Dict[str, Any] = card.get("set") or {}
            set_id = set_info.get("id")

            if set_id != current_set:
                if full_refresh and set_id:
                    existing = Set.query.filter_by(code=set_id).first()
                    if existing:
                        db.session.delete(existing)
                        db.session.commit()
                if isinstance(set_info.get("name"), dict):
                    set_info["name"] = _resolve_name(set_info.get("name"), lang)
                upsert_set(set_info)
                if current_set is not None:
                    db.session.commit()
                current_set = set_id

            card["name"] = _resolve_name(card.get("name"), lang)
            save_card_to_db(card)

        if current_set is not None:
            db.session.commit()


if __name__ == "__main__":
    app()
