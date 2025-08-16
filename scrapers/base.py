# scrapers/base.py
from typing import List, Optional
from pydantic import BaseModel, Field


class PriceResult(BaseModel):
    """
    Representa 1 item de preço retornado por um scraper.
    price_min_brl e price_max_brl devem estar em BRL.
    """
    query: str = Field(..., description="Termo pesquisado (ex.: 'Charizard 4/102')")
    source: str = Field(..., description="Identificador da fonte (ex.: 'mercadolivre')")
    title: str = Field(..., description="Título do anúncio/resultado")
    url: str = Field(..., description="URL do anúncio/resultado")
    price_min_brl: float = Field(..., ge=0)
    price_max_brl: float = Field(..., ge=0)

    # Extras opcionais (usados por PriceCharting, manter para compat)
    set_name: Optional[str] = None
    card_number: Optional[str] = None
    rarity: Optional[str] = None
    loose_price_brl: Optional[float] = None
    graded_price_brl: Optional[float] = None
    new_price_brl: Optional[float] = None
    trend_30d_pct: Optional[float] = None
    image_url: Optional[str] = None
    release_date: Optional[str] = None

    def clamp(self) -> "PriceResult":
        """Garante que min <= max; útil quando o parser pode inverter valores."""
        a = float(self.price_min_brl)
        b = float(self.price_max_brl)
        if a > b:
            a, b = b, a
        self.price_min_brl, self.price_max_brl = a, b
        return self


class BaseScraper:
    """
    Interface base dos scrapers.
    Todo scraper concreto deve definir `source_name` e implementar `search(query)`.
    """
    source_name: str = "base"

    def search(self, query: str) -> List[PriceResult]:
        """Retorna uma lista de PriceResult (min/max em BRL) para o termo."""
        raise NotImplementedError("Scraper precisa implementar .search(query)")
