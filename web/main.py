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
from pesquisa_produtos.scrapers.mercadolivre import MercadoLivreScraper


# ---------------------------------------------------------------------------
# Pydantic response models (contrato estável com o frontend)
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

def _shipping_out(s) -> ShippingOut:
    return ShippingOut(
        method=s.method, cost=s.cost, days=s.days,
        is_free=s.is_free, display_cost=s.display_cost,
        display_days=s.display_days,
    )


def _listing_to_out(listing: ProductListing) -> ListingOut:
    p = listing.product
    product_out = ProductOut(
        id=p.id, store=p.store, title=p.title, price=p.price,
        price_brl=p.price_brl, url=p.url, condition=p.condition,
        condition_label=p.condition_label, thumbnail=p.thumbnail,
        seller=p.seller, free_shipping=p.free_shipping,
        promotion=p.promotion, rating=p.rating,
    )
    ships = [_shipping_out(s) for s in listing.shipping_options]
    cheapest = _shipping_out(listing.cheapest_shipping) if listing.cheapest_shipping else None
    return ListingOut(
        product=product_out,
        shipping_options=ships,
        cheapest_shipping=cheapest,
        total=listing.total,
        total_brl=listing.total_brl,
    )


def _sort_listings(listings: list[ProductListing]) -> list[ProductListing]:
    def sort_key(l: ProductListing) -> float:
        best = l.cheapest_shipping
        if best is not None:
            return l.product.price + best.cost
        return l.product.price if l.product.free_shipping else l.product.price + 99999
    return sorted(listings, key=sort_key)


# ---------------------------------------------------------------------------
# App lifespan — scraper singleton
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scraper = MercadoLivreScraper()
    yield
    await app.state.scraper.close()


app = FastAPI(title="Pesquisa Produtos", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, request: Request):
    scraper: MercadoLivreScraper = request.app.state.scraper
    query = body.query.strip()
    cep = body.cep.strip().replace("-", "") if body.cep else None
    if cep and (len(cep) != 8 or not cep.isdigit()):
        cep = None

    try:
        products = await scraper.search(query, limit=12)
    except ConnectionError as e:
        return JSONResponse(status_code=429, content={"detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro ao buscar produtos: {e}"})

    if not products:
        return SearchResponse(query=query, cep=cep, results=[])

    if cep:
        tasks = [scraper.get_shipping(p, cep) for p in products]
        listings: list[ProductListing] = list(await asyncio.gather(*tasks))
    else:
        listings = [ProductListing(product=p) for p in products]

    sorted_listings = _sort_listings(listings)
    return SearchResponse(
        query=query,
        cep=cep or None,
        results=[_listing_to_out(l) for l in sorted_listings],
    )
