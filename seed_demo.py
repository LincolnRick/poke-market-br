"""seed_demo.py
-----------------
Popula o banco com dados sintéticos para demonstração do dashboard.

Executar na raiz do projeto com o ambiente virtual ativado:

    python seed_demo.py
"""

from __future__ import annotations

from datetime import datetime, timedelta
import random

from app import create_app
from db import db, Set, Card, PriceHistory

TERMS = [
    "Charizard 4/102",
    "Pikachu",
    "Mewtwo",
    "Gardevoir ex",
    "Miraidon ex",
]

SOURCES = ["pricecharting", "ebay"]


def _rand_price(base: float, spread: float = 0.15) -> tuple[float, float]:
    """Gera (min, max) ao redor de um ``base`` com certa variação percentual."""

    jitter = 1 + random.uniform(-spread, spread)
    mid = base * jitter
    lo = mid * (1 - 0.06 - random.uniform(0, 0.05))
    hi = mid * (1 + 0.06 + random.uniform(0, 0.05))
    lo, hi = round(max(1.0, lo), 2), round(max(lo + 0.01, hi), 2)
    return lo, hi


def main() -> None:
    app = create_app()
    with app.app_context():
        db.create_all()

        now = datetime.utcnow()

        # cria set e cartas básicas para associar valores
        demo_set = Set.query.filter_by(code="demo").first()
        if demo_set is None:
            demo_set = Set(name="Demo", code="demo")
            db.session.add(demo_set)
            db.session.flush()

        cards: dict[str, Card] = {}
        for i, term in enumerate(TERMS, start=1):
            card = Card.query.filter_by(set_id=demo_set.id, name=term).first()
            if card is None:
                card = Card(name=term, number=str(i), set_id=demo_set.id)
                db.session.add(card)
                db.session.flush()
            cards[term] = card

        base_map = {
            "Charizard 4/102": 1500.0,
            "Pikachu": 45.0,
            "Mewtwo": 120.0,
            "Gardevoir ex": 95.0,
            "Miraidon ex": 80.0,
        }

        rows: list[PriceHistory] = []
        for term in TERMS:
            base = base_map.get(term, 50.0)
            card = cards[term]
            for src in SOURCES:
                for k in range(8):
                    t = now - timedelta(days=7 - k, hours=random.randint(0, 12))
                    lo, hi = _rand_price(base * (1 + (k - 4) * 0.02))
                    mid = (lo + hi) / 2.0
                    rows.append(
                        PriceHistory(
                            card_id=card.id,
                            price=mid,
                            source=src,
                            captured_at=t,
                        )
                    )

        db.session.add_all(rows)
        db.session.commit()
        print(
            f"[seed_demo] Inseridos {len(rows)} registros para {len(TERMS)} cartas demo."
        )
        print(
            "[seed_demo] Abra: http://localhost:5000/  — e clique em algum termo do snapshot."
        )


if __name__ == "__main__":
    main()

