from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterator, Any
import re

import json5

# Regular expressions to strip TypeScript specific bits
_REF_RE = re.compile(r"\n?\s*(serie|series|set):\s*[A-Za-z_][A-Za-z0-9_]*,?")


def _parse_ts_object(content: str) -> Dict[str, Any]:
    """Parse a small TypeScript file containing a single exported object.

    The parser looks for the first opening and last closing curly braces and
    removes common references to imported variables (like ``set: Set``) before
    feeding the result to ``json5`` which tolerates trailing commas and single
    quotes.
    """

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    snippet = content[start : end + 1]
    snippet = _REF_RE.sub("", snippet)
    return json5.loads(snippet)


def _load_ts_file(path: Path) -> Dict[str, Any]:
    return _parse_ts_object(path.read_text(encoding="utf-8"))


def _build_series_map(data_root: Path) -> Dict[str, str]:
    """Map series directory names to their IDs."""
    mapping: Dict[str, str] = {}
    for serie_file in data_root.glob("*.ts"):
        try:
            data = _load_ts_file(serie_file)
            mapping[serie_file.stem] = str(data.get("id") or serie_file.stem)
        except Exception:
            continue
    return mapping


def parse_data(repo_path: Path, lang: str) -> Iterator[Dict[str, Any]]:
    """Yield card dictionaries from a local ``cards-database`` repository.

    Iterates over series and set folders, reading their TypeScript files and
    yielding one dictionary for each card with the set information attached.
    Administrative files like ``index.ts`` and ``types.ts`` are ignored.
    """

    data_root = repo_path / "data"
    series_map = _build_series_map(data_root)

    for serie_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        serie_id = series_map.get(serie_dir.name, "")
        for set_dir in sorted(p for p in serie_dir.iterdir() if p.is_dir()):
            set_file = serie_dir / f"{set_dir.name}.ts"
            if not set_file.exists():
                continue
            set_data = _load_ts_file(set_file)
            set_data.setdefault("id", set_file.stem)
            set_data["serie"] = serie_id

            card_files = [
                p
                for p in set_dir.glob("*.ts")
                if p.name not in {"index.ts", "types.ts"}
            ]
            for card_file in sorted(card_files):
                card_data = _load_ts_file(card_file)
                card_data.update(
                    {
                        "localId": card_file.stem,
                        "id": f"{set_data['id']}-{card_file.stem}",
                        "set": set_data,
                        "language": lang,
                    }
                )
                yield card_data
