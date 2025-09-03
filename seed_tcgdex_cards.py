"""seed_tcgdex_cards.py
---------------------------------
Seed de cartas utilizando os arquivos locais do repositório `tcgdex`.
Suporta tanto o formato JSON da `tcgdex/distribution` quanto os arquivos
TypeScript da `tcgdex/cards-database`.
"""

from __future__ import annotations

import argparse
import json5
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

# Placeholders for your project's modules
# Ensure these imports match your actual project structure
from app import create_app
from db import db
from scrapers import tcgdex_import


# ---------------------------------------------------------------------------
# UTILITIES
def _slugify(text: str) -> str:
    """Normalizes a string for simple comparison."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------------------
# PARSING
def _parse_ts_object(content: str, file_path: Path) -> Dict[str, Any]:
    """Extracts and parses a JSON-like object from a TypeScript file."""
    try:
        # Locate the beginning of the exported object. This usually comes after
        # an ``=`` or ``export default``. Using the first ``{`` directly could
        # accidentally pick up import statements like ``import { foo }``.
        match = re.search(r"(=|default)\s*{", content)
        if not match:
            return {}

        start = content.find("{", match.start())

        # Walk the file and capture a balanced JSON object starting at ``start``.
        depth = 0
        in_string = False
        quote_char = ""
        escape = False
        end = start
        for idx in range(start, len(content)):
            ch = content[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote_char:
                    in_string = False
                continue

            if ch in ('"', "'"):
                in_string = True
                quote_char = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break

        json_string = content[start:end]

        # Strip TypeScript specific constructs such as ``as const`` or
        # ``satisfies SomeType`` which are invalid in JSON.
        json_string = re.sub(r"\b(as|satisfies)\b[^,}\]]*", "", json_string)

        # Use json5 for flexibility (it supports comments and trailing commas).
        return json5.loads(json_string)
    except Exception as e:
        print(
            f"Warning: Error parsing file {file_path}, skipping. Reason: {e}")
        return {}


# ---------------------------------------------------------------------------
# DATABASE LOGIC
def _process_and_save_card(
    card_data: dict, set_info: dict, lang: str, series_id: str, local_id: str
) -> None:
    """Enriches card data and saves it to the database."""
    sid = set_info.get("id")
    card_data.setdefault("set", {})
    card_data["set"].setdefault("id", sid)
    card_data["set"].setdefault("name", set_info.get("name"))

    # Language resolution happens in ``save_card_to_db``,
    # so we keep multilingual fields as dictionaries.

    card_data["language"] = lang
    card_data["image_url"] = tcgdex_import.build_card_image_url(
        lang, series_id, sid, local_id
    )
    try:
        tcgdex_import.save_card_to_db(card_data)
    except Exception as exc:
        db.session.rollback()
        print(f"Error importing card {card_data.get('id')}: {exc}")


# ---------------------------------------------------------------------------
# IMPORT STRATEGIES
def _import_from_cardsdb(
    data_dir: Path, set_ids: Optional[Iterable[str]] = None, lang: str = "en"
) -> None:
    """Robustly imports data from the tcgdex/cards-database repository."""
    data_root = data_dir / "data"
    if not data_root.exists():
        print(f"Data directory not found at {data_root}")
        return

    # Map series to their IDs, ignoring non-data files
    series_map: Dict[str, str] = {}
    for serie_file in data_root.glob("*.ts"):
        if serie_file.stem in ['index', 'types']:
            continue
        serie_data = _parse_ts_object(
            serie_file.read_text(encoding="utf-8"), serie_file)
        series_map[serie_file.stem] = serie_data.get(
            "id") or serie_file.stem.lower()

    for serie_dir in data_root.iterdir():
        if not serie_dir.is_dir():
            continue
        serie_id = series_map.get(serie_dir.name, "")

        # Correct Logic: Iterate over subdirectories (which are the actual sets)
        for set_dir in serie_dir.iterdir():
            if not set_dir.is_dir():
                continue

            # Find the corresponding metadata .ts file for the directory
            set_file = serie_dir / f"{set_dir.name}.ts"
            if not set_file.exists():
                continue

            set_data = _parse_ts_object(
                set_file.read_text(encoding="utf-8"), set_file)
            sid = set_data.get("id")
            s_name = set_data.get("name", {}).get(lang) or next(
                iter(set_data.get("name", {}).values()), "")

            if not sid or (set_ids and sid not in set_ids and _slugify(s_name) not in set_ids):
                continue

            set_info = {"id": sid, "name": s_name, "serie": serie_id}
            set_obj = tcgdex_import.upsert_set(set_info)

            # The cards are inside the set directory we've already validated
            card_files = [p for p in set_dir.glob(
                "*.ts") if p.stem not in ['index', 'types']]
            print(
                f"[seed_tcgdex_cards] {set_obj.name}: {len(card_files)} cards")

            for card_path in card_files:
                number = card_path.stem
                card_data = _parse_ts_object(
                    card_path.read_text(encoding="utf-8"), card_path)
                if not card_data:
                    continue
                card_data["id"] = f"{sid}-{number}"
                _process_and_save_card(
                    card_data, set_info, lang, serie_id, number)

            try:
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                print(f"Error committing set {set_obj.name}: {exc}")


def _import_sets(data_dir: Path, set_ids: Optional[Iterable[str]] = None, lang: str = "pt") -> None:
    """Selects the import strategy based on the directory structure."""
    if (data_dir / "data").exists():
        _import_from_cardsdb(data_dir, set_ids, lang)
    else:
        print(f"Recognized directory structure not found in '{data_dir}'.")
        print("Expecting a 'data' folder for cards-database.")

# ---------------------------------------------------------------------------
# CLI


def main() -> None:
    """Main function to parse arguments and run the import."""
    parser = argparse.ArgumentParser(
        description="Seed cards using local TCGdex files.")
    parser.add_argument(
        "--sets", nargs="*", help="IDs or names of sets to import; if omitted, imports all")
    parser.add_argument("--lang", default="pt",
                        help="Data language (e.g., pt, en)")
    parser.add_argument(
        "--data-dir",
        default="../cards-database",
        help="Path to the local tcgdex/cards-database repository",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        # Build a more robust path from the script's location
        script_dir = Path(__file__).resolve().parent
        data_dir_path = (script_dir / args.data_dir).resolve()
        _import_sets(data_dir_path, args.sets, args.lang)


if __name__ == "__main__":
    main()
