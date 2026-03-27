"""Integração com a API do Mercado Livre (MLB - Brasil)."""
from __future__ import annotations

import os
from typing import Optional

import httpx

from pesquisa_produtos.models.product import Product, ProductListing, ShippingOption
from pesquisa_produtos.scrapers.base import BaseScraper
from pesquisa_produtos.utils.cache import CacheManager
from pesquisa_produtos.utils.rate_limiter import RateLimiter

ML_BASE = "https://api.mercadolibre.com"
ML_SITE = "MLB"  # Brasil


class MercadoLivreScraper(BaseScraper):
    store_name = "Mercado Livre"

    def __init__(
        self,
        cache: Optional[CacheManager] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self._token = os.getenv("ML_ACCESS_TOKEN", "")
        self._app_id = os.getenv("ML_APP_ID", "")
        self._app_secret = os.getenv("ML_APP_SECRET", "")

        rps = 10.0 if self._token else 2.0
        super().__init__(cache=cache, rate_limiter=rate_limiter or RateLimiter(rps))

    def _auth_headers(self) -> dict:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def ensure_token(self) -> None:
        """Obtém token via client_credentials se APP_ID+SECRET estiverem configurados."""
        if self._token:
            return
        if not (self._app_id and self._app_secret):
            raise PermissionError(
                "A API do Mercado Livre requer autenticação.\n\n"
                "Configure no arquivo .env:\n"
                "  ML_APP_ID=seu_app_id\n"
                "  ML_APP_SECRET=seu_app_secret\n\n"
                "Crie seu app gratuito em: https://developers.mercadolivre.com.br\n"
                "Ou informe um ML_ACCESS_TOKEN diretamente."
            )

        client = await self._get_client()
        resp = await client.post(
            f"{ML_BASE}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._app_id,
                "client_secret": self._app_secret,
            },
        )
        if resp.status_code != 200:
            raise PermissionError(
                f"Falha ao obter token ML (HTTP {resp.status_code}). "
                "Verifique ML_APP_ID e ML_APP_SECRET no .env."
            )
        self._token = resp.json()["access_token"]

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        condition: Optional[str] = None,   # "new" | "used"
        use_cache: bool = True,
    ) -> list[Product]:
        """
        Busca produtos no Mercado Livre via API.

        Endpoint: GET /sites/MLB/search?q=QUERY&limit=N
        Docs: https://developers.mercadolivre.com.br/pt_br/itens-e-buscas
        """
        await self.ensure_token()

        params: dict = {"q": query, "limit": min(limit, 50)}
        if min_price is not None:
            params["price_min"] = min_price
        if max_price is not None:
            params["price_max"] = max_price
        if condition in ("new", "used"):
            params["condition"] = condition

        url = f"{ML_BASE}/sites/{ML_SITE}/search"
        data = await self._request(
            url, params=params, extra_headers=self._auth_headers(), use_cache=use_cache
        )

        results = data.get("results", [])
        return [Product.from_ml_json(item) for item in results]

    async def get_shipping(
        self,
        product: Product,
        cep: str,
        use_cache: bool = True,
    ) -> ProductListing:
        """
        Consulta opções de frete para um produto e CEP via API do ML.

        Endpoint: GET /items/{id}/shipping_options?zip_code=CEP
        """
        cep_clean = cep.replace("-", "").strip()
        url = f"{ML_BASE}/items/{product.id}/shipping_options"
        params = {"zip_code": cep_clean}

        try:
            data = await self._request(
                url, params=params, extra_headers=self._auth_headers(), use_cache=use_cache
            )
        except Exception:
            return ProductListing(product=product)

        options = self._parse_shipping_options(data, product.free_shipping)
        return ProductListing(product=product, shipping_options=options)

    def _parse_shipping_options(self, data: dict, free_shipping: bool) -> list[ShippingOption]:
        options: list[ShippingOption] = []

        for option in data.get("options", []):
            name = option.get("name", "Padrão")
            cost = float(option.get("list_cost", option.get("cost", 0)))
            days = self._parse_days(option)
            is_free = cost == 0 or free_shipping

            options.append(ShippingOption(method=name, cost=cost, days=days, is_free=is_free))

        if not options and free_shipping:
            options.append(ShippingOption(method="Padrão ML", cost=0.0, days=0, is_free=True))

        return sorted(options, key=lambda s: s.cost)

    @staticmethod
    def _parse_days(option: dict) -> int:
        estimated = option.get("estimated_delivery_time", {})
        if not estimated:
            return 0

        offset = estimated.get("offset", {})
        if offset:
            days = offset.get("date", 0)
            return max(1, int(days * 0.7))

        unit = estimated.get("unit", "")
        value = estimated.get("value", 0)
        if unit in ("days", "hours"):
            return int(value) if unit == "days" else max(1, int(value) // 24)

        return 0
