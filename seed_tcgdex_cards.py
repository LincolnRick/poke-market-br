#!/usr/bin/env python3
"""Seed local database with cards from tcgdex/cards-database TypeScript files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional

import json5
from sqlalchemy.orm import Session
from sqlalchemy import text
from tqdm import tqdm

from cards_db import Card, Base, get_engine, DATABASE_URL


IMPORT_RE = re.compile(r"^import .*$", re.MULTILINE)


def _clean_ts(content: str, set_name: str) -> str:
    """Prepare TypeScript content for JSON5 parsing."""
    content = IMPORT_RE.sub("", content)
    content = content.replace("export default card", "")
    content = content.replace("const card: Card =", "const card =")
    content = re.sub(r"(\bset\s*:\s*)Set\b", rf"\1\"{set_name}\"", content)
    # remove prefix/suffix around object
    content = re.sub(r"^\s*const card\s*=\s*", "", content, count=1).strip()
    if content.endswith(";"):
        content = content[:-1]
    return content


def _parse_card_file(path: Path) -> Optional[dict]:
    series_name = path.parents[1].name
    set_name = path.parent.name
    raw = path.read_text(encoding="utf-8")
    data_txt = _clean_ts(raw, set_name)
    try:
        data = json5.loads(data_txt)
    except Exception as e:
        raise ValueError(f"parse error: {e}")
    return {
        "series_name": series_name,
        "set_name": set_name,
        "file_local_id": path.stem,
        "data": data,
    }


def iter_card_paths(root: Path):
    for p in root.glob("data/*/*/*.ts"):
        if p.name in {"index.ts", "types.ts"}:
            continue
        yield p


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed tcgdex cards from local files")
    parser.add_argument("--cards-db-dir", required=True, help="Path to cards-database root")
    parser.add_argument("--clean", action="store_true", help="Clean table before insert")
    parser.add_argument("--limit", type=int, help="Process only N cards")
    args = parser.parse_args()

    cards_root = Path(args.cards_db_dir).resolve()
    engine = get_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        if args.clean:
            session.execute(text("DELETE FROM cards"))
            session.commit()

        paths = list(iter_card_paths(cards_root))
        if args.limit is not None:
            paths = paths[: args.limit]

        inserted = updated = errors = 0
        for path in tqdm(paths, desc="cards"):
            try:
                info = _parse_card_file(path)
            except Exception as exc:
                print(f"error parsing {path}: {exc}")
                errors += 1
                continue

            data = info["data"]
            card_id = f"{info['series_name']}|{info['set_name']}|{info['file_local_id']}"
            types = data.get("types")
            types_json = json.dumps(types) if types is not None else None
            name_en = None
            name_pt = None
            name = data.get("name")
            if isinstance(name, dict):
                name_en = name.get("en")
                name_pt = name.get("pt")

            existing = session.get(Card, card_id)
            if existing:
                existing.series_name = info["series_name"]
                existing.set_name = info["set_name"]
                existing.file_local_id = info["file_local_id"]
                existing.name_en = name_en
                existing.name_pt = name_pt
                existing.rarity = data.get("rarity")
                existing.category = data.get("category")
                existing.types_json = types_json
                existing.data_json = data
                updated += 1
            else:
                session.add(
                    Card(
                        id=card_id,
                        series_name=info["series_name"],
                        set_name=info["set_name"],
                        file_local_id=info["file_local_id"],
                        name_en=name_en,
                        name_pt=name_pt,
                        rarity=data.get("rarity"),
                        category=data.get("category"),
                        types_json=types_json,
                        data_json=data,
                    )
                )
                inserted += 1

            if (inserted + updated) % 500 == 0:
                session.commit()

        session.commit()

    total = inserted + updated
    print(
        f"Processed {total} cards: {inserted} inserted, {updated} updated, {errors} errors."
    )
    print("Database URL:", DATABASE_URL)


if __name__ == "__main__":
    main()
