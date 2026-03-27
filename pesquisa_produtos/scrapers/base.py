"""Classe base abstrata para todos os scrapers/integrações de e-commerce."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from pesquisa_produtos.models.product import Product, ProductListing
from pesquisa_produtos.utils.cache import CacheManager
from pesquisa_produtos.utils.rate_limiter import RateLimiter

DEFAULT_HEADERS = {
    "User-Agent": "pesquisa-produtos/0.1.0",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "application/json",
}


class BaseScraper(ABC):
    store_name: str = ""

    def __init__(
        self,
        cache: Optional[CacheManager] = None,
        rate_limiter: Optional[RateLimiter] = None,
        requests_per_second: float = 2.0,
    ) -> None:
        self.cache = cache or CacheManager()
        self.rate_limiter = rate_limiter or RateLimiter(requests_per_second)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                timeout=httpx.Timeout(15.0, connect=5.0),
                follow_redirects=True,
            )
        return self._client

    async def _request(
        self,
        url: str,
        params: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
        use_cache: bool = True,
    ) -> Any:
        """GET com cache e rate limiting."""
        if use_cache:
            cached = self.cache.get(url, params)
            if cached is not None:
                return cached

        await self.rate_limiter.wait()
        client = await self._get_client()
        headers = extra_headers or {}
        response = client.build_request("GET", url, params=params, headers=headers)
        resp = await client.send(response)

        if resp.status_code == 403:
            raise PermissionError(
                f"API retornou 403 Forbidden para {url}. "
                "Configure ML_ACCESS_TOKEN no arquivo .env para autenticar."
            )
        if resp.status_code == 429:
            raise ConnectionError("Rate limit atingido. Aguarde alguns segundos e tente novamente.")

        resp.raise_for_status()
        data = resp.json()

        if use_cache:
            self.cache.set(url, data, params)

        return data

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @abstractmethod
    async def search(
        self, query: str, limit: int = 10, use_cache: bool = True
    ) -> list[Product]:
        """Busca produtos por palavra-chave. Retorna lista de Product."""
        ...

    @abstractmethod
    async def get_shipping(
        self, product: Product, cep: str, use_cache: bool = True
    ) -> ProductListing:
        """Consulta frete para o produto e CEP. Retorna ProductListing."""
        ...
