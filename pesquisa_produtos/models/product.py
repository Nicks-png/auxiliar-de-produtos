from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ShippingOption:
    method: str          # "PAC", "SEDEX", "Grátis", etc.
    cost: float
    days: int            # dias úteis estimados
    is_free: bool = False

    @property
    def display_cost(self) -> str:
        return "Grátis" if self.is_free or self.cost == 0 else f"R$ {self.cost:.2f}"

    @property
    def display_days(self) -> str:
        return f"{self.days}d úteis" if self.days else "—"


@dataclass
class Product:
    id: str
    store: str
    title: str
    price: float
    url: str
    currency: str = "BRL"
    condition: str = "new"          # "new" | "used"
    thumbnail: str = ""
    seller: str = ""
    available_quantity: int = 0
    free_shipping: bool = False
    promotion: Optional[str] = None   # ex: "Relâmpago 30% OFF"
    rating: Optional[float] = None
    scraped_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_ml_json(cls, data: dict) -> "Product":
        """Mapeia o JSON bruto da API do Mercado Livre para Product."""
        shipping = data.get("shipping", {})
        tags = data.get("tags", [])

        promotion = None
        if "good_quality_picture" in tags:
            pass
        if data.get("sale_price"):
            sale = data["sale_price"]
            if sale.get("type") == "promotion":
                pct = sale.get("metadata", {}).get("campaign_discount_percentage")
                promotion = f"Promoção {int(pct)}% OFF" if pct else "Promoção ativa"
        elif "brand_deal" in tags:
            promotion = "Brand Deal"
        elif "lightning_deal" in tags:
            promotion = "⚡ Relâmpago"

        seller = ""
        if data.get("seller"):
            seller = data["seller"].get("nickname", "")
        elif data.get("official_store_name"):
            seller = data["official_store_name"]

        return cls(
            id=data["id"],
            store="Mercado Livre",
            title=data.get("title", ""),
            price=float(data.get("price", 0)),
            url=data.get("permalink", ""),
            currency=data.get("currency_id", "BRL"),
            condition=data.get("condition", "new"),
            thumbnail=data.get("thumbnail", ""),
            seller=seller,
            available_quantity=data.get("available_quantity", 0),
            free_shipping=shipping.get("free_shipping", False),
            promotion=promotion,
            rating=data.get("reviews", {}).get("rating_average") if data.get("reviews") else None,
        )

    @property
    def condition_label(self) -> str:
        return "Novo" if self.condition == "new" else "Usado"

    @property
    def price_brl(self) -> str:
        return f"R$ {self.price:,.2f}"


@dataclass
class ProductListing:
    """Agrupa um Product com as opções de frete calculadas para um CEP."""
    product: Product
    shipping_options: list[ShippingOption] = field(default_factory=list)

    @property
    def cheapest_shipping(self) -> Optional[ShippingOption]:
        if not self.shipping_options:
            return None
        return min(self.shipping_options, key=lambda s: s.cost)

    @property
    def fastest_shipping(self) -> Optional[ShippingOption]:
        if not self.shipping_options:
            return None
        return min(self.shipping_options, key=lambda s: s.days or 999)

    @property
    def total(self) -> float:
        best = self.cheapest_shipping
        shipping_cost = best.cost if best else (0.0 if self.product.free_shipping else 0.0)
        return self.product.price + shipping_cost

    @property
    def total_brl(self) -> str:
        return f"R$ {self.total:,.2f}"
