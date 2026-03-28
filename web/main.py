from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from pesquisa_produtos.models.product import ProductListing
from pesquisa_produtos.scrapers.search import search_all
from pesquisa_produtos.utils.cache import CacheManager


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ShippingOut(BaseModel):
    method: str
    cost: float
    days: int
    is_free: bool
    display_cost: str
    display_days: str


class ProductOut(BaseModel):
    id: str
    store: str
    title: str
    price: float
    price_brl: str
    url: str
    condition: str
    condition_label: str
    thumbnail: str
    seller: str
    free_shipping: bool
    promotion: Optional[str] = None
    rating: Optional[float] = None


class ListingOut(BaseModel):
    product: ProductOut
    shipping_options: list[ShippingOut]
    cheapest_shipping: Optional[ShippingOut] = None
    total: float
    total_brl: str


class SearchResponse(BaseModel):
    query: str
    cep: Optional[str] = None
    results: list[ListingOut]


class SearchRequest(BaseModel):
    query: str
    cep: Optional[str] = None


class DealsRequest(BaseModel):
    categories: list[str] = []
    max_price: Optional[float] = None
    condition: Optional[str] = None   # "new" | "used" | "all" | None
    sort: Optional[str] = None        # "price" | "discount" | "rating" | "free_shipping"
    cep: Optional[str] = None


# ---------------------------------------------------------------------------
# Category → queries mapping
# ---------------------------------------------------------------------------

CATEGORY_QUERIES: dict[str, list[str]] = {
    "Eletrônicos":  ["fone de ouvido bluetooth", "monitor gamer"],
    "Games":        ["teclado gamer", "headset gamer"],
    "Casa":         ["airfryer", "aspirador robô"],
    "Moda":         ["tênis masculino", "bolsa feminina"],
    "Esportes":     ["whey protein", "bicicleta ergométrica"],
    "Smartphones":  ["smartphone samsung", "celular xiaomi"],
    "Livros":       ["livro best seller", "kindle"],
    "Beleza":       ["perfume importado", "protetor solar"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ship_out(s) -> ShippingOut:
    return ShippingOut(
        method=s.method, cost=s.cost, days=s.days,
        is_free=s.is_free, display_cost=s.display_cost, display_days=s.display_days,
    )


def _listing_to_out(listing: ProductListing) -> ListingOut:
    p = listing.product
    return ListingOut(
        product=ProductOut(
            id=p.id, store=p.store, title=p.title, price=p.price,
            price_brl=p.price_brl, url=p.url, condition=p.condition,
            condition_label=p.condition_label, thumbnail=p.thumbnail,
            seller=p.seller, free_shipping=p.free_shipping,
            promotion=p.promotion, rating=p.rating,
        ),
        shipping_options=[_ship_out(s) for s in listing.shipping_options],
        cheapest_shipping=_ship_out(listing.cheapest_shipping) if listing.cheapest_shipping else None,
        total=listing.total,
        total_brl=listing.total_brl,
    )


def _dedup(items: list[ListingOut]) -> list[ListingOut]:
    seen: set[str] = set()
    out: list[ListingOut] = []
    for item in items:
        key = item.product.title[:30].lower().strip()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _sort_deals(items: list[ListingOut], sort: Optional[str]) -> list[ListingOut]:
    if sort == "free_shipping":
        return sorted(items, key=lambda x: (not x.product.free_shipping, x.total))
    if sort == "rating":
        return sorted(items, key=lambda x: -(x.product.rating or 0))
    if sort == "discount":
        return sorted(items, key=lambda x: (x.product.promotion is None, x.total))
    return sorted(items, key=lambda x: x.total)  # "price" é o padrão


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Pesquisa Produtos", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest):
    query = body.query.strip()
    cep = body.cep.strip().replace("-", "") if body.cep else None
    if cep and (len(cep) != 8 or not cep.isdigit()):
        cep = None

    try:
        listings = await search_all(query=query, limit_per_store=8, cep=cep)
    except ConnectionError as e:
        return JSONResponse(status_code=429, content={"detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro ao buscar: {e}"})

    return SearchResponse(
        query=query, cep=cep or None,
        results=[_listing_to_out(l) for l in listings],
    )


@app.post("/deals", response_model=SearchResponse)
async def deals(body: DealsRequest):
    # Categorias → queries
    categories = body.categories or list(CATEGORY_QUERIES.keys())[:3]
    queries: list[str] = []
    for cat in categories:
        queries.extend(CATEGORY_QUERIES.get(cat, [])[:1])  # 1 query por categoria
    queries = list(dict.fromkeys(queries))[:6]             # deduplica e limita a 6

    cep = body.cep.strip().replace("-", "") if body.cep else None
    if cep and (len(cep) != 8 or not cep.isdigit()):
        cep = None

    condition = body.condition if body.condition not in (None, "all") else None

    shared_cache = CacheManager()
    try:
        tasks = [
            search_all(
                query=q,
                limit_per_store=3,
                cep=cep,
                max_price=body.max_price,
                condition=condition,
                cache=shared_cache,
            )
            for q in queries
        ]
        results_per_query = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro ao buscar ofertas: {e}"})

    all_out: list[ListingOut] = []
    for r in results_per_query:
        if isinstance(r, Exception):
            continue
        all_out.extend(_listing_to_out(l) for l in r)

    all_out = _dedup(all_out)
    all_out = _sort_deals(all_out, body.sort)

    label = ", ".join(categories)
    return SearchResponse(query=label, cep=cep, results=all_out)
