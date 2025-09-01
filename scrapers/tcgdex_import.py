"""scrapers/tcgdex_import.py
-------------------------------
Importador de cartas usando a API TCGdex (pt-br).
Armazena dados básicos das cartas em um SQLite local.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import requests
from sqlalchemy import Column, Float, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# Caminho padrão do banco (mesmo arquivo utilizado pelo app principal)
DB_PATH = "instance/poke_market.db"
DB_URL = f"sqlite:///{DB_PATH}"

# Garante que a pasta exista
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Conexão SQLAlchemy
engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class CardPTBR(Base):
    """Modelo de carta importada do TCGdex."""

    __tablename__ = "cards_ptbr"

    id = Column(String, primary_key=True)
    local_id = Column(String)
    nome = Column(String)
    raridade = Column(String)
    tipo = Column(String)
    categoria = Column(String)
    set_id = Column(String)
    set_nome = Column(String)
    ilustrador = Column(String)
    imagem_url = Column(String)
    preco_usd = Column(Float)
    preco_eur = Column(Float)
    preco_trend = Column(Float)
    preco_avg7 = Column(Float)


# Cria tabela se não existir
Base.metadata.create_all(engine)

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


def save_card_to_db(card_data: Dict[str, Any], session: Session) -> None:
    """Upsert da carta no banco usando o id como chave primária."""
    cid = card_data.get("id")
    if not cid:
        return
    try:
        card = session.get(CardPTBR, cid)
        if card is None:
            card = CardPTBR(id=cid)
            session.add(card)
        card.local_id = card_data.get("localId")
        card.nome = card_data.get("name")
        card.raridade = card_data.get("rarity")
        card.tipo = (card_data.get("types") or [None])[0]
        card.categoria = card_data.get("category")
        set_info = card_data.get("set") or {}
        card.set_id = set_info.get("id")
        card.set_nome = set_info.get("name")
        card.ilustrador = card_data.get("illustrator")
        card.imagem_url = (
            card_data.get("image")
            or (card_data.get("images") or {}).get("large")
            or (card_data.get("images") or {}).get("small")
        )
        prices = card_data.get("prices") or {}
        card.preco_usd = prices.get("usd")
        card.preco_eur = prices.get("eur")
        card.preco_trend = prices.get("trend")
        card.preco_avg7 = prices.get("avg7")
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        print(f"Erro ao salvar carta {cid}: {exc}")


def main() -> None:
    """Fluxo principal: importa todas as cartas da API."""
    session = SessionLocal()
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
                save_card_to_db(card, session)
            except Exception as exc:  # noqa: BLE001
                print(f"Erro ao processar carta {card.get('id')}: {exc}")
    session.close()


if __name__ == "__main__":
    main()
