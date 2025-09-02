"""scrapers/tcgdex_import.py
-------------------------------
Importador de cartas usando a API TCGdex (pt-br).
Armazena dados básicos das cartas em um SQLite local.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry
from http.client import RemoteDisconnected

from db import db, Set, Card, PriceHistory, CardAttack, CardAbility


API_SETS = "https://api.tcgdex.net/v2/pt-br/sets"
API_CARDS = "https://api.tcgdex.net/v2/pt-br/cards"

# Imagem de placeholder para cartas sem imagem disponível
PLACEHOLDER_IMG = (
    "https://claudia.abril.com.br/wp-content/uploads/2020/01/pokemons-do-pokemon-go_6.jpg"
    "?quality=70&strip=all&w=720&crop=1"
)


session = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)


def get_all_sets() -> List[Dict[str, Any]]:
    """Obtém todos os conjuntos disponíveis em pt-br."""
    try:
        resp = session.get(API_SETS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except RequestException as exc:
        print(f"Erro ao obter conjuntos: {exc}")
        return []


def get_set(set_id: str) -> Dict[str, Any]:
    """Obtém informações detalhadas de um set específico."""
    url = f"{API_SETS}/{set_id}"
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except RequestException as exc:
        print(f"Erro ao obter set {set_id}: {exc}")
        return {}


def fetch_card_detail(card_id: str) -> Dict[str, Any]:
    """Obtém detalhes completos de uma carta específica com retry simples."""
    url = f"{API_CARDS}/{card_id}"
    backoff = 1
    for attempt in range(5):
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except RequestException as exc:
            print(
                f"Erro ao obter carta {card_id} (tentativa {attempt + 1}/5): {exc}"
            )
            cause = getattr(exc, "__cause__", None)
            if isinstance(cause, RemoteDisconnected):
                sleep(backoff)
                backoff += 1
                continue
            sleep(backoff)
            backoff += 1
    print(f"Falha ao obter carta {card_id} após 5 tentativas")
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

    series = set_data.get("serie") or set_data.get("series")
    if series:
        if isinstance(series, dict):
            series = series.get("name") or series.get("id") or str(series)
        set_obj.series = series

    total_cards = set_data.get("total") or set_data.get("totalCards")
    if total_cards is None:
        cards = set_data.get("cards")
        if isinstance(cards, list):
            total_cards = len(cards)
    if total_cards is not None:
        try:
            set_obj.total_cards = int(total_cards)
        except (TypeError, ValueError):
            pass

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

    series = tcgdex_set.get("serie") or tcgdex_set.get("series")
    if series:
        if isinstance(series, dict):
            series = series.get("name") or series.get("id") or str(series)
        set_obj.series = series

    total_cards = tcgdex_set.get("total") or tcgdex_set.get("totalCards")
    if total_cards is None:
        cards = tcgdex_set.get("cards")
        if isinstance(cards, list):
            total_cards = len(cards)
    if total_cards is not None:
        try:
            set_obj.total_cards = int(total_cards)
        except (TypeError, ValueError):
            pass

    db.session.flush()
    return set_obj


def _first_str(value: Any) -> Optional[str]:
    """Retorna a primeira string encontrada em estruturas aninhadas."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for v in value.values():
            result = _first_str(v)
            if result:
                return result
    if isinstance(value, list):
        for v in value:
            result = _first_str(v)
            if result:
                return result
    return None


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

    images = card_data.get("images") or {}
    image_url = (
        _first_str(card_data.get("image"))
        or _first_str(card_data.get("imageUrl"))
        or _first_str(images.get("large"))
        or _first_str(images.get("small"))
        or _first_str(images)
    )

    db.session.flush()  # garante que card.id exista para salvar a imagem
    local_dir = Path("static/cards")
    local_dir.mkdir(parents=True, exist_ok=True)

    saved_path = PLACEHOLDER_IMG
    if image_url:
        urls_to_try = [image_url]
        base_url = image_url.split("?")[0]
        if not base_url.lower().endswith((".png", ".jpg", ".jpeg")):
            urls_to_try.extend([f"{image_url}.png", f"{image_url}.jpg"])
        last_exc: RequestException | None = None
        for url in urls_to_try:
            try:
                resp = session.get(url, timeout=15)
                resp.raise_for_status()
                suffix = ".png" if url.lower().endswith(".png") else ".jpg"
                with open(local_dir / f"{card.id}{suffix}", "wb") as f:
                    f.write(resp.content)
                saved_path = f"cards/{card.id}{suffix}"
                break
            except RequestException as exc:
                last_exc = exc
        else:
            print(f"Erro ao baixar imagem {image_url}: {last_exc}")

    card.image_url = saved_path
    card.language = card_data.get("language") or "português"

    card.hp = card_data.get("hp")
    card.category = card_data.get("category") or card_data.get("supertype")
    subtypes = card_data.get("subtypes")
    card.subtypes = subtypes if isinstance(subtypes, list) else None
    card.evolves_from = card_data.get("evolvesFrom") or card_data.get("evolves_from")
    card.illustrator = card_data.get("illustrator")
    card.weaknesses = card_data.get("weaknesses")
    card.resistances = card_data.get("resistances")
    retreat_cost = card_data.get("retreatCost")
    card.retreat_cost = retreat_cost if isinstance(retreat_cost, list) else None
    card.flavor_text = card_data.get("flavorText") or card_data.get("flavor_text")
    card.border = card_data.get("border")
    variants = card_data.get("variants") or {}
    if isinstance(variants, dict):
        card.holo = variants.get("holo")
        card.material = variants.get("material")
        card.edition = variants.get("edition")
    else:
        card.holo = card_data.get("holo")
        card.material = card_data.get("material")
        card.edition = card_data.get("edition")
    card.legalities = card_data.get("legalities")

    db.session.flush()

    prices = card_data.get("prices")
    price_value = _extract_price(prices)
    if price_value is not None:
        db.session.add(
            PriceHistory(card_id=card.id, price=float(price_value), source="tcgdex")
        )

    attacks = card_data.get("attacks")
    if isinstance(attacks, list):
        CardAttack.query.filter_by(card_id=card.id).delete()
        for atk in attacks:
            name = atk.get("name")
            if not name:
                continue
            db.session.add(
                CardAttack(
                    card_id=card.id,
                    name=name,
                    cost=atk.get("cost"),
                    damage=atk.get("damage"),
                    text=atk.get("text") or atk.get("effect"),
                )
            )

    abilities = card_data.get("abilities")
    if isinstance(abilities, list):
        CardAbility.query.filter_by(card_id=card.id).delete()
        for ability in abilities:
            name = ability.get("name")
            if not name:
                continue
            db.session.add(
                CardAbility(
                    card_id=card.id,
                    name=name,
                    cost=ability.get("cost"),
                    damage=ability.get("damage"),
                    text=ability.get("text") or ability.get("effect"),
                )
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
