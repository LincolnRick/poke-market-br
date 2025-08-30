#!/usr/bin/env python3
"""Script para criar e popular o banco de dados do Pokémon TCG em PT-BR.

Uso:
    python popular_bd.py
O script lê a variável de ambiente `DATABASE_URL` para a conexão
(como ``postgresql://usuario:senha@localhost:5432/pokemontcg``).
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, text

ARQUIVO_ESQUEMA = Path(__file__).with_name("esquema_tcg_ptbr.sql")

ENERGIAS = [
    ("Grama", "G"),
    ("Fogo", "R"),
    ("Água", "W"),
    ("Raio", "L"),
    ("Psíquico", "P"),
    ("Luta", "F"),
    ("Escuridão", "D"),
    ("Metal", "M"),
    ("Fada", "Y"),
    ("Dragão", "N"),
    ("Incolor", "C"),
]

RARIDADES = [
    "Comum",
    "Incomum",
    "Rara",
    "Rara Holo",
    "Ultra Rara",
    "Secreta",
]


def obter_engine():
    url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/pokemontcg")
    return create_engine(url, echo=False)


def criar_esquema(engine):
    """Executa o arquivo SQL para criar todo o esquema."""
    with engine.begin() as conn:
        sql = ARQUIVO_ESQUEMA.read_text(encoding="utf-8")
        conn.execute(text(sql))


def popular_basicos(engine):
    """Insere registros básicos como tipos de energia e raridades."""
    with engine.begin() as conn:
        for nome, simbolo in ENERGIAS:
            conn.execute(
                text(
                    "INSERT INTO tipos_energia (nome, simbolo) VALUES (:nome, :simbolo) "
                    "ON CONFLICT (nome) DO NOTHING"
                ),
                {"nome": nome, "simbolo": simbolo},
            )
        for nome in RARIDADES:
            conn.execute(
                text(
                    "INSERT INTO raridades (nome) VALUES (:nome) ON CONFLICT (nome) DO NOTHING"
                ),
                {"nome": nome},
            )


if __name__ == "__main__":
    engine = obter_engine()
    criar_esquema(engine)
    popular_basicos(engine)
    print("Esquema criado e dados básicos inseridos com sucesso.")
