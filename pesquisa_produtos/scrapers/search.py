"""
Busca em todas as lojas em paralelo e combina os resultados.
Ponto de entrada único para CLI e web app.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from pesquisa_produtos.models.product import Product, ProductListing
from pesquisa_produtos.scrapers.mercadolivre import MercadoLivreScraper
from pesquisa_produtos.scrapers.magalu import MagaluScraper
from pesquisa_produtos.utils.cache import CacheManager


def _make_scrapers(cache: Optional[CacheManager] = None) -> list:
    shared_cache = cache or CacheManager()
    return [
        MercadoLivreScraper(cache=shared_cache),
        MagaluScraper(cache=shared_cache),
    ]


async def search_all(
    query: str,
    limit_per_store: int = 8,
    cep: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    condition: Optional[str] = None,
    use_cache: bool = True,
    cache: Optional[CacheManager] = None,
) -> list[ProductListing]:
    """
    Busca em todas as lojas em paralelo.
    Retorna lista de ProductListing ordenada por menor total (preço + frete).
    """
    scrapers = _make_scrapers(cache)

    # ── Busca em paralelo ──────────────────────────────────────────────────
    search_tasks = [
        s.search(
            query,
            limit=limit_per_store,
            min_price=min_price,
            max_price=max_price,
            condition=condition,
            use_cache=use_cache,
        )
        for s in scrapers
    ]
    store_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    # Achata e ignora lojas que falharam
    all_products: list[tuple] = []  # (scraper, product)
    for scraper, result in zip(scrapers, store_results):
        if isinstance(result, Exception):
            continue
        for product in result:
            all_products.append((scraper, product))

    if not all_products:
        for s in scrapers:
            await s.close()
        return []

    # ── Frete em paralelo (se CEP fornecido) ───────────────────────────────
    if cep:
        cep_clean = cep.replace("-", "").strip()
        shipping_tasks = [
            scraper.get_shipping(product, cep_clean, use_cache=use_cache)
            for scraper, product in all_products
        ]
        listings: list[ProductListing] = list(
            await asyncio.gather(*shipping_tasks, return_exceptions=False)
        )
    else:
        listings = [ProductListing(product=p) for _, p in all_products]

    # ── Fecha clientes ─────────────────────────────────────────────────────
    for s in scrapers:
        await s.close()

    # ── Ordena por menor total ─────────────────────────────────────────────
    return sorted(listings, key=_sort_key)


def _sort_key(listing: ProductListing) -> float:
    best = listing.cheapest_shipping
    if best is not None:
        return listing.product.price + best.cost
    if listing.product.free_shipping:
        return listing.product.price
    return listing.product.price + 99_999
