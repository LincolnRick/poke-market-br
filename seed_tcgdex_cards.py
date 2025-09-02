"""seed_tcgdex_cards.py
---------------------------------
Seed de cartas utilizando os arquivos locais do repositório `tcgdex`.
Suporta tanto o formato JSON da `tcgdex/distribution` quanto os arquivos
TypeScript da `tcgdex/cards-database`.

Uso:
    python seed_tcgdex_cards.py                               # importa todos os sets
    python seed_tcgdex_cards.py --sets base4                   # por ID do set
    python seed_tcgdex_cards.py --sets "Base Set 2"           # por nome
    python seed_tcgdex_cards.py --data-dir ../cards-database   # caminho dos dados
"""

from __future__ import annotations

import argparse
import json
import json5
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app import create_app
from db import db
from scrapers import tcgdex_import


# ---------------------------------------------------------------------------
# Utilidades


def _slugify(text: str) -> str:
    """Normaliza uma string para comparação simples."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _load_sets(data_root: Path, lang: str) -> list[dict]:
    """Carrega metadados dos sets a partir do index.json.

    Se o idioma solicitado não possuir dados de sets, faz fallback para inglês.
    """
    sets_path = data_root / lang / "sets" / "index.json"
    data: list[dict] = []
    if sets_path.exists():
        try:
            with sets_path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except json.JSONDecodeError:
            data = []
    if not data:
        fallback = data_root / "en" / "sets" / "index.json"
        if fallback.exists():
            with fallback.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
    return data


def _format_set(raw: dict) -> dict:
    """Adapta o formato do set para o tcgdex_import."""
    card_count = raw.get("cardCount") or {}
    images = {"symbol": raw.get("symbol"), "logo": raw.get("logo")}
    series_match = re.search(r"/[a-z]{2}/([^/]+)/", raw.get("logo") or "")
    serie = series_match.group(1) if series_match else ""
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "images": images,
        "total": card_count.get("official") or card_count.get("total"),
        "serie": serie,
    }


def _resolve_sets(identifiers: Iterable[str], sets_data: list[dict]) -> list[dict]:
    """Retorna metadados de sets a partir de IDs ou nomes."""
    by_id = {s.get("id"): s for s in sets_data if s.get("id")}
    by_name = {_slugify(s.get("name", "")): s for s in sets_data if s.get("name")}

    result = []
    for ident in identifiers:
        ident = ident.strip()
        data = by_id.get(ident) or by_name.get(_slugify(ident))
        if data:
            result.append(data)
        else:
            print(f"Set não encontrado: {ident}")
    return result


def _gather_cards(cards_root: Path, set_id: str) -> list[Path]:
    """Retorna caminhos dos arquivos de cartas pertencentes a um set."""
    return list(cards_root.glob(f"{set_id}-*/index.json"))


# ---------------------------------------------------------------------------
# Parsing helpers for cards-database (.ts) files


def _parse_ts_object(content: str) -> Dict[str, Any]:
    """Converte um objeto TypeScript simples em dict Python."""
    # Remove imports e export
    content = re.sub(r"^import[^\n]*\n", "", content, flags=re.MULTILINE)
    content = re.sub(r"export default [^\n]*", "", content)
    # Remove declarações "const foo: Tipo ="
    content = re.sub(r"const [^=]+=", "", content)
    # Remove referência direta ao objeto Set dentro das cartas
    content = re.sub(r"\n?\s*set:\s*Set,?", "", content)
    content = content.strip()
    return json5.loads(content)


# ---------------------------------------------------------------------------
# Importação


def _import_from_distribution(
    data_dir: Path, set_ids: Optional[Iterable[str]] = None, lang: str = "pt"
) -> None:
    """Importa sets e cartas usando os arquivos JSON da tcgdex/distribution."""
    data_root = data_dir / "v2"
    lang_dir = data_root / lang
    cards_root = lang_dir / "cards"

    sets_data = [_format_set(s) for s in _load_sets(data_root, lang)]
    if set_ids:
        sets_data = _resolve_sets(set_ids, sets_data)

    cards_index_path = cards_root / "index.json"
    cards_map: dict[str, list[str]] = defaultdict(list)
    if cards_index_path.exists():
        with cards_index_path.open("r", encoding="utf-8") as fp:
            cards_index = json.load(fp)
        for entry in cards_index:
            cid = entry.get("id", "")
            sid = cid.split("-", 1)[0]
            cards_map[sid].append(cid)

    for set_info in sets_data:
        sid = set_info.get("id")
        if not sid:
            continue
        set_obj = tcgdex_import.upsert_set(set_info)

        if cards_map:
            card_ids = cards_map.get(sid, [])
            card_files = [cards_root / cid / "index.json" for cid in card_ids]
        else:
            card_files = _gather_cards(cards_root, sid)

        print(f"[seed_tcgdex_cards] {set_obj.name}: {len(card_files)} cartas")
        for card_path in card_files:
            try:
                with card_path.open("r", encoding="utf-8") as fp:
                    card = json.load(fp)
            except json.JSONDecodeError as exc:
                print(f"Erro lendo {card_path}: {exc}")
                continue

            card.setdefault("set", {})
            card["set"].setdefault("id", sid)
            card["set"].setdefault("name", set_info.get("name"))
            card["set"].setdefault("images", set_info.get("images"))
            card["language"] = lang
            series_id = set_info.get("serie") or ""
            local_id = card.get("localId") or ""
            card["image_url"] = tcgdex_import.build_card_image_url(
                lang, series_id, sid, local_id
            )

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


def _import_from_cardsdb(
    data_dir: Path, set_ids: Optional[Iterable[str]] = None, lang: str = "en"
) -> None:
    """Importa dados diretamente do repositório tcgdex/cards-database."""
    data_root = data_dir / "data"
    if not data_root.exists():
        print(f"Diretório de dados não encontrado em {data_root}")
        return

    # Mapeia séries para obter seus IDs
    series_map: Dict[str, str] = {}
    for serie_file in data_root.glob("*.ts"):
        serie_name = serie_file.stem
        serie_data = _parse_ts_object(serie_file.read_text())
        serie_id = serie_data.get("id") or serie_name.lower()
        series_map[serie_name] = serie_id

    for serie_dir in data_root.iterdir():
        if not serie_dir.is_dir():
            continue
        serie_name = serie_dir.name
        serie_id = series_map.get(serie_name, "")

        for set_file in serie_dir.glob("*.ts"):
            set_name = set_file.stem
            set_data = _parse_ts_object(set_file.read_text())
            sid = set_data.get("id")
            if not sid:
                continue
            if set_ids and sid not in set_ids and _slugify(set_name) not in set_ids:
                continue

            set_info = {
                "id": sid,
                "name": set_data.get("name", {}).get(lang)
                or next(iter(set_data.get("name", {}).values()), ""),
                "serie": serie_id,
            }
            set_obj = tcgdex_import.upsert_set(set_info)

            card_dir = serie_dir / set_name
            card_files = list(card_dir.glob("*.ts")) if card_dir.exists() else []
            print(f"[seed_tcgdex_cards] {set_obj.name}: {len(card_files)} cartas")
            for card_path in card_files:
                number = card_path.stem
                card_data = _parse_ts_object(card_path.read_text())
                card_data["localId"] = number
                card_data["id"] = f"{sid}-{number}"
                card_data["set"] = set_info
                card_data["language"] = lang
                card_data["image_url"] = tcgdex_import.build_card_image_url(
                    lang, serie_id, sid, number
                )
                try:
                    tcgdex_import.save_card_to_db(card_data)
                except Exception as exc:  # noqa: BLE001
                    db.session.rollback()
                    print(f"Erro ao importar carta {card_data.get('id')}: {exc}")
            try:
                db.session.commit()
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                print(f"Erro ao commitar set {set_obj.name}: {exc}")


def _import_sets(data_dir: Path, set_ids: Optional[Iterable[str]] = None, lang: str = "pt") -> None:
    """Seleciona a estratégia de importação conforme a estrutura do diretório."""
    if (data_dir / "v2").exists():
        _import_from_distribution(data_dir, set_ids, lang)
    else:
        _import_from_cardsdb(data_dir, set_ids, lang)


# ---------------------------------------------------------------------------
# CLI


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed de cartas usando arquivos locais da TCGdex.",
    )
    parser.add_argument(
        "--sets",
        nargs="*",
        help="IDs ou nomes dos sets a importar; se omitido, importa todos",
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Idioma dos dados (ex: en, pt)",
    )
    parser.add_argument(
        "--data-dir",
        default="../cards-database",
        help="Caminho para o repositório local tcgdex/cards-database ou distribution",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        _import_sets(Path(args.data_dir), args.sets, args.lang)


if __name__ == "__main__":
    main()
