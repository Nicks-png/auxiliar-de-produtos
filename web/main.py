from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Pydantic response models
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


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # scrapers são criados por requisição via search_all


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
        query=query,
        cep=cep or None,
        results=[_listing_to_out(l) for l in listings],
    )
