"""
Scraper da Magazine Luiza via HTML público.
Raspa magazineluiza.com.br sem autenticação.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from bs4 import BeautifulSoup, Tag

from pesquisa_produtos.models.product import Product, ProductListing, ShippingOption
from pesquisa_produtos.scrapers.base import BaseScraper
from pesquisa_produtos.utils.cache import CacheManager
from pesquisa_produtos.utils.rate_limiter import RateLimiter

MAGALU_SEARCH = "https://www.magazineluiza.com.br/busca/{slug}/"


class MagaluScraper(BaseScraper):
    store_name = "Magazine Luiza"

    def __init__(
        self,
        cache: Optional[CacheManager] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        super().__init__(cache=cache, rate_limiter=rate_limiter or RateLimiter(1.0))

    # ── Busca ─────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        condition: Optional[str] = None,
        use_cache: bool = True,
    ) -> list[Product]:
        slug = re.sub(r"\s+", "+", query.strip())
        url = MAGALU_SEARCH.format(slug=slug)

        html = await self._fetch_html(url, use_cache=use_cache)
        products = self._parse_results(html, limit)

        if min_price:
            products = [p for p in products if p.price >= min_price]
        if max_price:
            products = [p for p in products if p.price <= max_price]

        return products

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_results(self, html: str, limit: int) -> list[Product]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select('[data-testid="product-card-container"]')
        products: list[Product] = []
        for card in cards[:limit]:
            product = self._parse_card(card)
            if product:
                products.append(product)
        return products

    def _parse_card(self, card: Tag) -> Optional[Product]:
        try:
            # ── Título ──────────────────────────────────────────────────────
            title_el = card.select_one('[data-testid="product-title"]')
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            if not title:
                return None

            # ── Preço (preferimos o preço Pix/à vista sobre o parcelado) ───
            price = self._parse_price(card)
            if price is None:
                return None

            # ── Link ────────────────────────────────────────────────────────
            link_el = card.select_one("a[href]")
            raw_url = str(link_el["href"]) if link_el and link_el.get("href") else ""
            if raw_url.startswith("/"):
                raw_url = "https://www.magazineluiza.com.br" + raw_url
            url = raw_url

            # ── ID ──────────────────────────────────────────────────────────
            item_id = self._extract_id(url) or str(uuid.uuid4())[:12]

            # ── Thumbnail ───────────────────────────────────────────────────
            img_el = card.select_one('[data-testid="image"] img') or card.select_one("img")
            thumbnail = ""
            if img_el:
                thumbnail = str(img_el.get("data-src") or img_el.get("src") or "")

            # ── Frete ───────────────────────────────────────────────────────
            ship_el = card.select_one('[data-testid="productCard-shipping-tag"]')
            free_shipping = False
            if ship_el:
                ship_text = ship_el.get_text().lower()
                free_shipping = "grátis" in ship_text or "gratis" in ship_text

            # ── Promoção / cupom ────────────────────────────────────────────
            promo = None
            coupon_el = card.select_one('[data-testid="productCard-coupon"]')
            if coupon_el:
                promo = coupon_el.get_text(strip=True)

            # ── Rating ──────────────────────────────────────────────────────
            rating_el = card.select_one('[data-testid="review"]')
            rating: Optional[float] = None
            if rating_el:
                m = re.match(r"([\d.]+)", rating_el.get_text(strip=True))
                if m:
                    try:
                        rating = float(m.group(1))
                    except ValueError:
                        pass

            return Product(
                id=item_id,
                store="Magazine Luiza",
                title=title,
                price=price,
                url=url,
                currency="BRL",
                condition="new",
                thumbnail=thumbnail,
                seller="Magazine Luiza",
                available_quantity=1,
                free_shipping=free_shipping,
                promotion=promo,
                rating=rating,
            )
        except Exception:
            return None

    @staticmethod
    def _parse_price(card: Tag) -> Optional[float]:
        """
        Preferência: preço Pix/à vista ([data-testid=price-value])
        Fallback: preço original ([data-testid=price-original])
        """
        for testid in ("price-value", "price-original", "price-default"):
            el = card.select_one(f'[data-testid="{testid}"]')
            if not el:
                continue
            text = el.get_text(strip=True)
            # Remove prefixos como "ou", "R$", pontos de milhar, troca vírgula por ponto
            text = re.sub(r"[^\d,]", "", text).replace(",", ".")
            # Pega o primeiro número válido
            numbers = re.findall(r"\d+\.?\d*", text)
            for n in numbers:
                try:
                    val = float(n)
                    if val > 1:
                        return val
                except ValueError:
                    continue
        return None

    @staticmethod
    def _extract_id(url: str) -> Optional[str]:
        # Magalu URLs terminam em /p/XXXXXX/
        m = re.search(r"/p/([a-z0-9]+)/", url, re.IGNORECASE)
        return f"MLZ-{m.group(1)}" if m else None

    # ── Frete ─────────────────────────────────────────────────────────────────

    async def get_shipping(
        self,
        product: Product,
        cep: str,
        use_cache: bool = True,
    ) -> ProductListing:
        if product.free_shipping:
            return ProductListing(
                product=product,
                shipping_options=[
                    ShippingOption(method="Frete grátis", cost=0.0, days=2, is_free=True)
                ],
            )
        return ProductListing(product=product)
