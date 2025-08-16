# scripts/seed_demo.py
"""
Seed de dados DEMO para o dashboard.
Cria algumas linhas no banco com preços sintéticos, só para validar UI.

Como usar:
    # no terminal, na raiz do projeto
    # (garanta que o venv está ativo)
    python scripts/seed_demo.py
"""

from __future__ import annotations
from datetime import datetime, timedelta
import random

from flask import Flask

from config import DB_URL
from db import DB, Price

TERMS = [
    "Charizard 4/102",
    "Pikachu",
    "Mewtwo",
    "Gardevoir ex",
    "Miraidon ex",
]

SOURCES = ["pricecharting", "ebay"]  # mantém “ebay” só para compor o snapshot


def _mk_app() -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = DB_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    DB.init_app(app)
    return app


def _rand_price(base: float, spread: float = 0.15) -> tuple[float, float]:
    """
    Gera (min, max) ao redor de um 'base' com certa variação percentual.
    """
    jitter = 1 + random.uniform(-spread, spread)
    mid = base * jitter
    lo = mid * (1 - 0.06 - random.uniform(0, 0.05))   # ~6–11% abaixo
    hi = mid * (1 + 0.06 + random.uniform(0, 0.05))   # ~6–11% acima
    lo, hi = round(max(1.0, lo), 2), round(max(lo + 0.01, hi), 2)
    return lo, hi


def main() -> None:
    app = _mk_app()
    with app.app_context():
        DB.create_all()

        now = datetime.utcnow()

        # limpa um pouco (opcional): comente se não quiser apagar nada
        # DB.session.query(Price).delete()

        rows = []
        base_map = {
            "Charizard 4/102": 1500.0,
            "Pikachu": 45.0,
            "Mewtwo": 120.0,
            "Gardevoir ex": 95.0,
            "Miraidon ex": 80.0,
        }

        for i, term in enumerate(TERMS):
            base = base_map.get(term, 50.0)

            # gera 8 pontos históricos pra cada fonte, espaçados no tempo
            for src in SOURCES:
                for k in range(8):
                    t = now - timedelta(days=7 - k, hours=random.randint(0, 12))
                    lo, hi = _rand_price(base * (1 + (k - 4) * 0.02))  # leve tendência
                    p = Price(
                        query=term,
                        source=src,
                        title=f"{term} — demo ({src})",
                        url="https://example.org/demo",
                        price_min_brl=lo,
                        price_max_brl=hi,
                        captured_at=t,
                    )
                    rows.append(p)

        DB.session.add_all(rows)
        DB.session.commit()
        print(f"[seed_demo] Inseridos {len(rows)} registros em {len(TERMS)} termos / {len(SOURCES)} fontes.")
        print("[seed_demo] Abra: http://localhost:5000/  — e clique em algum termo do snapshot.")

if __name__ == "__main__":
    main()
