# db.py
# -----------------------------------------------------------------------------
# Camada de modelos e acesso ao banco para o app estilo "Collectr".
# Melhorias desta versão:
# - Constraints e índices para integridade e performance
# - Unicidade por (set_id, number) para não duplicar a mesma carta
# - CHECKs para quantidade e preços não negativos
# - Timestamps padronizados
# - Histórico de preços (PriceHistory) por carta
# - Propriedades auxiliares (ex.: total_value estimado de um item)
# - Métodos utilitários de serialização (as_dict)
# -----------------------------------------------------------------------------

from __future__ import annotations

from datetime import datetime, date
from typing import Optional, Dict, Any, List

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    Index,
    func,
    select,
    ForeignKey,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

# Instância global do SQLAlchemy (inicializada em app.py via db.init_app(app))
db = SQLAlchemy()


# -----------------------------------------------------------------------------
# MODELOS
# -----------------------------------------------------------------------------

class Set(db.Model):
    """
    Conjunto (set) de cartas.
    """
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(120), nullable=False, index=True)
    code: Mapped[Optional[str]] = mapped_column(db.String(32), unique=True, index=True)
    release_date: Mapped[date] = mapped_column(default=date.today, nullable=False)
    icon_url: Mapped[Optional[str]] = mapped_column(db.String(300))
    series: Mapped[Optional[str]] = mapped_column(db.String(120))
    total_cards: Mapped[Optional[int]] = mapped_column(db.Integer)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relacionamentos
    cards: Mapped[List["Card"]] = relationship(
        "Card", back_populates="set", lazy=True, cascade="all, delete-orphan"
    )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "release_date": None if self.release_date is None else self.release_date.isoformat(),
            "icon_url": self.icon_url,
            "series": self.series,
            "total_cards": self.total_cards,
        }

    def __repr__(self) -> str:
        return f"<Set id={self.id} name={self.name!r} code={self.code!r}>"


class Card(db.Model):
    """
    Carta individual pertencente a um Set.
    Unicidade garantida por (set_id, number) para evitar duplicatas do mesmo número.
    """
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("set_id", "number", name="uq_card_set_number"),
        Index("ix_card_name_set", "name", "set_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(200), nullable=False, index=True)
    number: Mapped[Optional[str]] = mapped_column(db.String(20), index=True)
    rarity: Mapped[Optional[str]] = mapped_column(db.String(50))
    type: Mapped[Optional[str]] = mapped_column(db.String(50))
    image_url: Mapped[Optional[str]] = mapped_column(db.String(500))
    hp: Mapped[Optional[str]] = mapped_column(db.String(10))
    category: Mapped[Optional[str]] = mapped_column(db.String(50))
    subtypes: Mapped[Optional[List[str]]] = mapped_column(db.JSON)
    evolves_from: Mapped[Optional[str]] = mapped_column(db.String(100))
    illustrator: Mapped[Optional[str]] = mapped_column(db.String(100))
    weaknesses: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(db.JSON)
    resistances: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(db.JSON)
    retreat_cost: Mapped[Optional[List[str]]] = mapped_column(db.JSON)
    flavor_text: Mapped[Optional[str]] = mapped_column(db.Text)
    language: Mapped[Optional[str]] = mapped_column(db.String(20))
    border: Mapped[Optional[str]] = mapped_column(db.String(20))
    holo: Mapped[Optional[str]] = mapped_column(db.String(30))
    material: Mapped[Optional[str]] = mapped_column(db.String(30))
    edition: Mapped[Optional[str]] = mapped_column(db.String(30))

    set_id: Mapped[int] = mapped_column(
        ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relacionamentos
    set: Mapped[Set] = relationship("Set", back_populates="cards", lazy="joined")
    price_history: Mapped[List["PriceHistory"]] = relationship(
        "PriceHistory", back_populates="card", lazy=True, cascade="all, delete-orphan"
    )
    attacks: Mapped[List["CardAttack"]] = relationship(
        "CardAttack", back_populates="card", lazy=True, cascade="all, delete-orphan"
    )
    abilities: Mapped[List["CardAbility"]] = relationship(
        "CardAbility", back_populates="card", lazy=True, cascade="all, delete-orphan"
    )

    def latest_price(self) -> Optional[float]:
        """
        Retorna o preço mais recente do histórico dessa carta, se houver.
        """
        if not self.id:
            return None
        # Consulta única para pegar o último registro
        row = db.session.execute(
            select(PriceHistory.price).where(PriceHistory.card_id == self.id).order_by(
                PriceHistory.captured_at.desc()
            ).limit(1)
        ).first()
        return None if row is None else float(row[0])

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "number": self.number,
            "rarity": self.rarity,
            "type": self.type,
            "image_url": self.image_url,
            "hp": self.hp,
            "category": self.category,
            "subtypes": self.subtypes,
            "evolves_from": self.evolves_from,
            "illustrator": self.illustrator,
            "weaknesses": self.weaknesses,
            "resistances": self.resistances,
            "retreat_cost": self.retreat_cost,
            "flavor_text": self.flavor_text,
            "language": self.language,
            "border": self.border,
            "holo": self.holo,
            "material": self.material,
            "edition": self.edition,
            "attacks": [a.as_dict() for a in self.attacks],
            "abilities": [a.as_dict() for a in self.abilities],
            "set": self.set.as_dict() if self.set else None,
            "latest_price": self.latest_price(),
        }

    def __repr__(self) -> str:
        return f"<Card id={self.id} name={self.name!r} number={self.number!r} set_id={self.set_id}>"


class CardAttack(db.Model):
    """Ataque associado a uma carta."""
    __tablename__ = "card_attacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    cost: Mapped[Optional[List[str]]] = mapped_column(db.JSON)
    damage: Mapped[Optional[str]] = mapped_column(db.String(50))
    text: Mapped[Optional[str]] = mapped_column(db.Text)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relacionamentos
    card: Mapped[Card] = relationship("Card", back_populates="attacks")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "cost": self.cost,
            "damage": self.damage,
            "text": self.text,
        }


class CardAbility(db.Model):
    """Habilidade associada a uma carta."""
    __tablename__ = "card_abilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    cost: Mapped[Optional[List[str]]] = mapped_column(db.JSON)
    damage: Mapped[Optional[str]] = mapped_column(db.String(50))
    text: Mapped[Optional[str]] = mapped_column(db.Text)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relacionamentos
    card: Mapped[Card] = relationship("Card", back_populates="abilities")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "cost": self.cost,
            "damage": self.damage,
            "text": self.text,
        }


class CollectionItem(db.Model):
    """
    Item na coleção do usuário (quantidade, condição, preços, etc.).
    """
    __tablename__ = "collection_items"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_collectionitem_quantity_nonneg"),
        CheckConstraint(
            "(purchase_price IS NULL) OR (purchase_price >= 0.0)",
            name="ck_collectionitem_purchase_price_nonneg",
        ),
        CheckConstraint(
            "(last_price IS NULL) OR (last_price >= 0.0)",
            name="ck_collectionitem_last_price_nonneg",
        ),
        Index("ix_collectionitem_card_created", "card_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(default=1, nullable=False)
    condition: Mapped[str] = mapped_column(db.String(20), default="NM", nullable=False)  # NM, LP, MP, HP, DMG
    grade: Mapped[Optional[str]] = mapped_column(db.String(10))  # Ex.: PSA 10, CGC 9, etc.
    purchase_price: Mapped[Optional[float]] = mapped_column(db.Float)  # preço pago por unidade
    last_price: Mapped[Optional[float]] = mapped_column(db.Float)      # preço estimado atual por unidade
    location: Mapped[Optional[str]] = mapped_column(db.String(120))    # Binder A / Box 1 / Toploader, etc.
    notes: Mapped[Optional[str]] = mapped_column(db.Text)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relacionamentos
    card: Mapped[Card] = relationship("Card", lazy="joined")

    @property
    def unit_estimated_value(self) -> float:
        """
        Valor unitário estimado para o item:
        - prioriza last_price (campo do item),
        - se não houver, usa latest_price da carta,
        - se ainda não houver, cai para purchase_price,
        - senão 0.0.
        """
        if self.last_price is not None:
            return float(self.last_price)
        if self.card is not None:
            lp = self.card.latest_price()
            if lp is not None:
                return float(lp)
        if self.purchase_price is not None:
            return float(self.purchase_price)
        return 0.0

    @property
    def total_estimated_value(self) -> float:
        """
        Valor total estimado = unit_estimated_value * quantity.
        """
        q = int(self.quantity or 0)
        return self.unit_estimated_value * q

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "card": self.card.as_dict() if self.card else None,
            "quantity": self.quantity,
            "condition": self.condition,
            "grade": self.grade,
            "purchase_price": self.purchase_price,
            "last_price": self.last_price,
            "location": self.location,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "unit_estimated_value": self.unit_estimated_value,
            "total_estimated_value": self.total_estimated_value,
        }

    def __repr__(self) -> str:
        return f"<CollectionItem id={self.id} card_id={self.card_id} qty={self.quantity}>"


class WishlistItem(db.Model):
    """
    Item na lista de desejos (wishlist) do usuário.
    """
    __tablename__ = "wishlist_items"
    __table_args__ = (
        CheckConstraint(
            "(target_price IS NULL) OR (target_price >= 0.0)",
            name="ck_wishlistitem_target_price_nonneg",
        ),
        Index("ix_wishlist_card_added", "card_id", "added_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_price: Mapped[Optional[float]] = mapped_column(db.Float)
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    # Relacionamentos
    card: Mapped[Card] = relationship("Card", lazy="joined")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "card": self.card.as_dict() if self.card else None,
            "target_price": self.target_price,
            "added_at": self.added_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<WishlistItem id={self.id} card_id={self.card_id}>"


class PriceHistory(db.Model):
    """
    Histórico de preços por carta.
    Permite registrar origem e data de captura para auditoria.
    """
    __tablename__ = "price_history"
    __table_args__ = (
        CheckConstraint("price >= 0.0", name="ck_pricehistory_price_nonneg"),
        Index("ix_pricehistory_card_captured", "card_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price: Mapped[float] = mapped_column(db.Float, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(db.String(64))  # ex.: 'manual', 'tcgplayer', 'ebay', 'stub'
    captured_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    # Relacionamentos
    card: Mapped[Card] = relationship("Card", back_populates="price_history", lazy="joined")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "card_id": self.card_id,
            "price": self.price,
            "source": self.source,
            "captured_at": self.captured_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<PriceHistory id={self.id} card_id={self.card_id} price={self.price}>"


# -----------------------------------------------------------------------------
# HELPERS/QUERIES AGREGADAS (podem ser úteis no app.py)
# -----------------------------------------------------------------------------

def kpi_total_items() -> int:
    """
    Soma de quantidades na coleção.
    """
    value = db.session.query(func.coalesce(func.sum(CollectionItem.quantity), 0)).scalar()
    return int(value or 0)


def kpi_unique_cards() -> int:
    """
    Qtde de cartas distintas na coleção.
    """
    value = db.session.query(func.count(func.distinct(CollectionItem.card_id))).scalar()
    return int(value or 0)


def kpi_wishlist_count() -> int:
    """
    Total de itens na wishlist.
    """
    value = db.session.query(func.count(WishlistItem.id)).scalar()
    return int(value or 0)


def kpi_total_estimated_value() -> float:
    """
    Valor estimado total da coleção.
    Prioriza last_price do item; se nulo, tenta latest_price da carta; se nulo, usa purchase_price.
    Implementado em Python para refletir a lógica de fallback com precisão.
    """
    total = 0.0
    # Carregamos os itens com a carta associada (lazy='joined' no modelo já ajuda)
    for item in CollectionItem.query.all():
        total += item.total_estimated_value
    return round(total, 2)
