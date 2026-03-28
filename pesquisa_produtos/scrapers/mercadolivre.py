"""
Scraper do Mercado Livre via HTML público — sem API, sem token.
Raspa diretamente lista.mercadolivre.com.br usando o layout poly-card atual.
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

ML_SEARCH = "https://lista.mercadolivre.com.br/{slug}"


class MercadoLivreScraper(BaseScraper):
    store_name = "Mercado Livre"

    def __init__(
        self,
        cache: Optional[CacheManager] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        super().__init__(cache=cache, rate_limiter=rate_limiter or RateLimiter(1.5))

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
        slug = re.sub(r"\s+", "-", query.strip())
        url = ML_SEARCH.format(slug=slug)

        params: dict = {}
        if min_price:
            params["price_from"] = int(min_price)
        if max_price:
            params["price_to"] = int(max_price)
        if condition == "new":
            params["ITEM_CONDITION"] = "2230284"
        elif condition == "used":
            params["ITEM_CONDITION"] = "2230285"

        html = await self._fetch_html(url, params=params or None, use_cache=use_cache)
        return self._parse_results(html, limit)

    # ── Parsing dos cards ──────────────────────────────────────────────────────

    def _parse_results(self, html: str, limit: int) -> list[Product]:
        soup = BeautifulSoup(html, "html.parser")

        # Layout atual: ol com li.ui-search-layout__item
        cards = soup.select("li.ui-search-layout__item")
        if not cards:
            # Fallback para layouts antigos
            cards = soup.select("li[class*='results__item']")

        products: list[Product] = []
        for card in cards[:limit]:
            product = self._parse_card(card)
            if product:
                products.append(product)

        return products

    def _parse_card(self, card: Tag) -> Optional[Product]:
        try:
            # ── Título ──────────────────────────────────────────────────────
            title_el = (
                card.select_one(".poly-component__title")
                or card.select_one("[class*='component__title']")
                or card.select_one("h2")
            )
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            if not title:
                return None

            # ── Link ────────────────────────────────────────────────────────
            link_el = (
                card.select_one("a[href*='mercadolivre']")
                or card.select_one("a[href*='mlstatic']")
                or card.select_one("a")
            )
            url = str(link_el["href"]) if link_el and link_el.get("href") else ""

            # ── ID do item ──────────────────────────────────────────────────
            item_id = self._extract_id(url) or str(uuid.uuid4())[:12]

            # ── Preço ───────────────────────────────────────────────────────
            price = self._parse_price(card)
            if price is None:
                return None

            # ── Thumbnail ───────────────────────────────────────────────────
            img_el = card.select_one("img[src]") or card.select_one("img")
            thumbnail = ""
            if img_el:
                thumbnail = str(img_el.get("data-src") or img_el.get("src") or "")

            # ── Frete ───────────────────────────────────────────────────────
            shipping_el = card.select_one(".poly-component__shipping")
            free_shipping = False
            if shipping_el:
                ship_text = shipping_el.get_text().lower()
                free_shipping = "grátis" in ship_text or "gratis" in ship_text

            # ── Vendedor ────────────────────────────────────────────────────
            seller_el = (
                card.select_one(".poly-component__seller")
                or card.select_one("[class*='seller']")
                or card.select_one("[class*='store']")
            )
            seller = seller_el.get_text(strip=True) if seller_el else ""

            # ── Condição ────────────────────────────────────────────────────
            cond_el = card.select_one("[class*='condition']") or card.select_one("[class*='highlight']")
            condition_text = cond_el.get_text(strip=True).lower() if cond_el else ""
            condition = "used" if "usado" in condition_text else "new"

            # ── Promoção / desconto ─────────────────────────────────────────
            promo = self._parse_promotion(card)

            return Product(
                id=item_id,
                store="Mercado Livre",
                title=title,
                price=price,
                url=url,
                currency="BRL",
                condition=condition,
                thumbnail=thumbnail,
                seller=seller,
                available_quantity=1,
                free_shipping=free_shipping,
                promotion=promo,
            )
        except Exception:
            return None

    @staticmethod
    def _parse_price(card: Tag) -> Optional[float]:
        """
        Pega o preço atual (ignora preço riscado / antigo).
        O ML usa .andes-money-amount--previous para o preço original riscado.
        """
        # Encontra o primeiro bloco de preço que NÃO seja o preço anterior
        for amount in card.select(".andes-money-amount"):
            classes = " ".join(amount.get("class", []))
            if "previous" in classes or "discount" in classes:
                continue
            fraction_el = amount.select_one(".andes-money-amount__fraction")
            if not fraction_el:
                continue
            fraction = fraction_el.get_text(strip=True).replace(".", "").replace(",", "")
            cents_el = amount.select_one(".andes-money-amount__cents")
            cents = cents_el.get_text(strip=True)[:2] if cents_el else "00"
            try:
                return float(f"{fraction}.{cents}")
            except ValueError:
                continue

        # Fallback: regex no texto bruto
        text = card.get_text()
        matches = re.findall(r"R\$\s*\xa0?\s*([\d.]+)(?:[,\xa0](\d{2}))?", text)
        for groups in matches:
            try:
                val = float(groups[0].replace(".", ""))
                if val > 1:
                    return val
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_id(url: str) -> Optional[str]:
        m = re.search(r"(MLB-?\d+)", url)
        return m.group(1).replace("-", "") if m else None

    @staticmethod
    def _parse_promotion(card: Tag) -> Optional[str]:
        # Badge de desconto percentual
        discount_el = card.select_one(".andes-money-amount__discount")
        if discount_el:
            txt = discount_el.get_text(strip=True)
            if txt:
                return txt

        # Tags tipo "OFERTA DO DIA", "MAIS VENDIDO"
        for sel in [".poly-component__highlight", "[class*='highlight']", ".andes-tag"]:
            el = card.select_one(sel)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) < 50:
                    return txt
        return None

    # ── Frete ─────────────────────────────────────────────────────────────────

    async def get_shipping(
        self,
        product: Product,
        cep: str,
        use_cache: bool = True,
    ) -> ProductListing:
        """
        Extrai informações de frete da página do produto.
        Se já tem frete grátis pelo campo do card, retorna direto.
        """
        if product.free_shipping:
            return ProductListing(
                product=product,
                shipping_options=[
                    ShippingOption(method="Chegada grátis", cost=0.0, days=3, is_free=True)
                ],
            )

        if not product.url:
            return ProductListing(product=product)

        try:
            html = await self._fetch_html(product.url, use_cache=use_cache)
            options = self._parse_product_shipping(html)
            return ProductListing(product=product, shipping_options=options)
        except Exception:
            return ProductListing(product=product)

    @staticmethod
    def _parse_product_shipping(html: str) -> list[ShippingOption]:
        soup = BeautifulSoup(html, "html.parser")
        options: list[ShippingOption] = []

        # Seção de frete na página do produto
        for sel in [
            "[class*='shipping-summary']",
            "[class*='shipping']",
            "[class*='envio']",
        ]:
            section = soup.select_one(sel)
            if section:
                text = section.get_text().lower()
                if "grátis" in text or "gratis" in text:
                    options.append(ShippingOption(method="Padrão", cost=0.0, days=3, is_free=True))
                    return options
                # Tenta extrair custo
                matches = re.findall(r"r\$\s*([\d.,]+)", text)
                for m in matches:
                    try:
                        cost = float(m.replace(".", "").replace(",", "."))
                        if cost > 0:
                            options.append(
                                ShippingOption(method="Padrão", cost=cost, days=5, is_free=False)
                            )
                            return options
                    except ValueError:
                        continue
                break

        return options
