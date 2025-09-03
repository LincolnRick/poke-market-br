"""load_tcgdex
================

Script de linha de comando para carregar os dados do repositório
``tcgdex/cards-database`` em um banco configurado pelo projeto
``poke-market-br``. O objetivo é permitir a importação offline dos
metadados de sets e cartas utilizando apenas arquivos locais.

Recursos principais
-------------------

* CLI baseada em ``typer`` com diversas opções de filtragem
* Parsing de arquivos TypeScript do repositório ``cards-database``
* Upsert idempotente de sets e cartas utilizando os modelos existentes
  em ``db.py``
* Barra de progresso via ``tqdm`` e saída enriquecida com ``rich``
* Suporte a importação incremental e modo *dry run*

Exemplos
--------

.. code-block:: bash

    python load_tcgdex.py --repo-path ../cards-database --lang pt --full-refresh
    DATABASE_URL=sqlite:///my.db python load_tcgdex.py --repo-path ../cards-db \
        --since 2024-01-01 --dry-run

O script reutiliza as funções ``upsert_set`` e ``save_card_to_db`` já
presentes em ``scrapers.tcgdex_import`` para garantir consistência com o
restante do projeto.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import json5
import orjson
import typer
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table
from tqdm import tqdm

from app import create_app
from db import Set, db
from scrapers.tcgdex_import import save_card_to_db, upsert_set


# ---------------------------------------------------------------------------
# Utilidades gerais
# ---------------------------------------------------------------------------

console = Console()


try:  # pragma: no cover - dependência opcional
    from unidecode import unidecode  # type: ignore
except Exception:  # pragma: no cover - fallback minimalista
    import unicodedata

    def unidecode(value: str) -> str:
        """Fallback simples removendo acentos usando ``unicodedata``."""

        norm = unicodedata.normalize("NFKD", value)
        return "".join(c for c in norm if not unicodedata.combining(c))


_IMPORT_RE = re.compile(r"^import[^\n]*\n", re.MULTILINE)
_EXPORT_RE = re.compile(r"export default [^\n]*")
_CONST_RE = re.compile(r"const [^=]+=", re.MULTILINE)
_SET_REF_RE = re.compile(r"\n?\s*set:\s*Set,?")


def _parse_ts_object(content: str) -> Dict[str, Any]:
    """Converte o conteúdo de um arquivo TypeScript simples em ``dict``.

    Remove declarações de import/export e converte o objeto resultante usando
    ``json5`` para lidar com comentários, aspas simples e vírgulas finais.
    """

    content = _IMPORT_RE.sub("", content)
    content = _EXPORT_RE.sub("", content)
    content = _CONST_RE.sub("", content)
    content = _SET_REF_RE.sub("", content)
    content = content.strip()
    return json5.loads(content)


def _load_ts_file(path: Path) -> Dict[str, Any]:
    """Lê um arquivo ``.ts`` e retorna seu conteúdo parseado."""

    return _parse_ts_object(path.read_text(encoding="utf-8"))


def _slugify(text: str) -> str:
    """Normalização básica para comparação de strings."""

    return re.sub(r"[^a-z0-9]+", "-", unidecode(text).lower()).strip("-")


def _build_series_map(data_root: Path) -> Dict[str, str]:
    """Mapeia diretórios de série para seus respectivos IDs."""

    series_map: Dict[str, str] = {}
    for serie_file in data_root.glob("*.ts"):
        try:
            data = _load_ts_file(serie_file)
            sid = data.get("id") or serie_file.stem.lower()
            series_map[serie_file.stem] = str(sid)
        except Exception:  # pragma: no cover - arquivo inválido
            continue
    return series_map


def _resolve_name(raw: Any, lang: str, fallback_en: bool) -> str:
    """Obtém o nome no idioma desejado com possíveis fallbacks."""

    if isinstance(raw, dict):
        name = raw.get(lang)
        if not name and fallback_en:
            name = raw.get("en")
        if not name:
            name = next(iter(raw.values()), "")
        return str(name)
    return str(raw or "")


# ---------------------------------------------------------------------------
# Modelos Pydantic (apenas para validação básica)
# ---------------------------------------------------------------------------


class SetData(BaseModel, extra="allow"):
    """Modelo Pydantic para o objeto de set vindo da cards-database."""

    id: str
    name: Dict[str, str] | str = Field(..., description="Nome do set")
    images: Dict[str, Any] | None = None
    cardCount: Dict[str, int] | None = None


class CardData(BaseModel, extra="allow"):
    """Modelo Pydantic para cartas da cards-database."""

    id: str
    localId: str
    name: Dict[str, str] | str
    set: Dict[str, Any]


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------


app = typer.Typer(help="Carrega dados do tcgdex/cards-database para o banco.")


@app.command("load")
def cli(  # noqa: PLR0913 - Muitos parâmetros são necessários para a CLI
    repo_path: Path = typer.Option(..., "--repo-path", exists=True, file_okay=False, dir_okay=True, help="Caminho para o repositório cards-database"),
    lang: List[str] = typer.Option(["pt"], "--lang", help="Idioma(s) a importar", show_default=True),
    only_sets: Optional[List[str]] = typer.Option(None, "--only-sets", help="Importa apenas os sets informados"),
    exclude_sets: Optional[List[str]] = typer.Option(None, "--exclude-sets", help="Ignora os sets informados"),
    since: Optional[str] = typer.Option(None, help="Importa somente arquivos alterados desde esta data (YYYY-MM-DD)"),
    full_refresh: bool = typer.Option(False, "--full-refresh/--no-full-refresh", help="Recria dados dos sets importados"),
    chunk_size: int = typer.Option(50, "--chunk-size", help="Tamanho do commit por lote", show_default=True),
    dry_run: bool = typer.Option(False, "--dry-run", help="Processa sem gravar no banco"),
    fallback_en: bool = typer.Option(False, "--fallback-en", help="Usa inglês como fallback de idioma"),
) -> None:
    """Executa a importação dos dados a partir dos arquivos locais."""

    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            console.print(f"[red]Data inválida: {since}[/red]")
            raise typer.Exit(code=1)

    normalized_only = {_slugify(s) for s in only_sets} if only_sets else set()
    normalized_exclude = {_slugify(s) for s in exclude_sets} if exclude_sets else set()

    data_root = repo_path / "data"
    if not data_root.exists():
        console.print(f"[red]Diretório {data_root} não encontrado[/red]")
        raise typer.Exit(code=1)

    series_map = _build_series_map(data_root)

    flask_app = create_app()
    processed_sets = 0
    processed_cards = 0

    with flask_app.app_context():
        if dry_run:
            db.session.begin_nested()

        for serie_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
            serie_id = series_map.get(serie_dir.name, "")
            for set_file in sorted(serie_dir.glob("*.ts")):
                set_mtime = datetime.fromtimestamp(set_file.stat().st_mtime)
                if since_dt and set_mtime < since_dt:
                    continue

                set_raw = _load_ts_file(set_file)
                set_model = SetData.model_validate(set_raw)

                sid = set_model.id
                name_slug = _slugify(_resolve_name(set_model.name, "en", True))
                if normalized_only and sid not in normalized_only and name_slug not in normalized_only:
                    continue
                if normalized_exclude and (sid in normalized_exclude or name_slug in normalized_exclude):
                    continue

                card_dir = serie_dir / set_file.stem
                card_files = sorted(card_dir.glob("*.ts"))
                if since_dt:
                    card_files = [p for p in card_files if datetime.fromtimestamp(p.stat().st_mtime) >= since_dt]
                    if not card_files:
                        continue

                processed_sets += 1

                for lang_code in lang:
                    set_dict = {
                        "id": sid,
                        "name": _resolve_name(set_model.name, lang_code, fallback_en),
                        "images": set_model.images or {},
                        "total": (set_model.cardCount or {}).get("official")
                        or (set_model.cardCount or {}).get("total"),
                        "serie": serie_id,
                    }

                    if full_refresh:
                        existing = Set.query.filter_by(code=sid).first()
                        if existing:
                            db.session.delete(existing)
                            db.session.commit()

                    set_obj = upsert_set(set_dict)

                    progress = tqdm(card_files, desc=f"{sid} [{lang_code}]", unit="card")
                    for idx, card_path in enumerate(progress, start=1):
                        card_raw = _load_ts_file(card_path)
                        card_raw.update(
                            {
                                "localId": card_path.stem,
                                "id": f"{sid}-{card_path.stem}",
                                "set": set_dict,
                                "language": lang_code,
                            }
                        )

                        card_model = CardData.model_validate(card_raw)
                        card_model.name = _resolve_name(card_model.name, lang_code, fallback_en)

                        try:
                            save_card_to_db(card_model.model_dump())
                            processed_cards += 1
                        except Exception as exc:  # pragma: no cover - log de erro
                            db.session.rollback()
                            console.print(f"[red]Erro ao salvar carta {card_model.id}: {exc}[/red]")

                        if not dry_run and chunk_size and idx % chunk_size == 0:
                            try:
                                db.session.commit()
                            except Exception as exc:  # pragma: no cover
                                db.session.rollback()
                                console.print(f"[red]Erro ao commitar lote: {exc}[/red]")

                    if not dry_run:
                        try:
                            db.session.commit()
                        except Exception as exc:  # pragma: no cover
                            db.session.rollback()
                            console.print(f"[red]Erro ao commitar set {set_obj.code}: {exc}[/red]")

        if dry_run:
            db.session.rollback()

    table = Table(title="Importação TCGdex")
    table.add_column("Sets")
    table.add_column("Cartas")
    table.add_row(str(processed_sets), str(processed_cards))
    console.print(table)

    # Também exibe um resumo em JSON utilizando ``orjson``
    console.log(orjson.dumps({"sets": processed_sets, "cards": processed_cards}).decode())


if __name__ == "__main__":
    app()

