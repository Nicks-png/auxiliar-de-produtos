"""Ponto de entrada da CLI. Comandos finos — toda lógica fica nos scrapers/utils."""
from __future__ import annotations

import asyncio
import sys
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Confirm, Prompt

load_dotenv()  # carrega .env antes de qualquer import que leia os vars

from pesquisa_produtos.models.product import ProductListing
from pesquisa_produtos.scrapers.mercadolivre import MercadoLivreScraper
from pesquisa_produtos.utils.cache import CacheManager
from pesquisa_produtos.utils import display

app = typer.Typer(
    name="pesquisa-produtos",
    help="[bold cyan]Assistente de compras inteligente[/bold cyan] — compare preços em e-commerces brasileiros.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
cache_app = typer.Typer(help="Gerenciar cache local de buscas.")
app.add_typer(cache_app, name="cache")

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cep_prompt() -> Optional[str]:
    cep = Prompt.ask(
        "[cyan]CEP para calcular frete[/cyan] (Enter para pular)",
        default="",
        console=console,
    )
    cep = cep.strip().replace("-", "")
    return cep if len(cep) == 8 and cep.isdigit() else None


def _sort_listings(listings: list[ProductListing]) -> list[ProductListing]:
    """Ordena por total (preço + menor frete). Sem frete consulta = preço."""
    def sort_key(l: ProductListing) -> float:
        best = l.cheapest_shipping
        if best is not None:
            return l.product.price + best.cost
        if l.product.free_shipping:
            return l.product.price
        return l.product.price + 99999  # sem info de frete vai pro final

    return sorted(listings, key=sort_key)


async def _run_search(
    query: str,
    limit: int,
    cep: Optional[str],
    no_cache: bool,
    min_price: Optional[float],
    max_price: Optional[float],
    condition: Optional[str],
) -> list[ProductListing]:
    scraper = MercadoLivreScraper()
    try:
        with console.status(f"[cyan]Buscando '{query}' no Mercado Livre…[/cyan]"):
            products = await scraper.search(
                query,
                limit=limit,
                min_price=min_price,
                max_price=max_price,
                condition=condition,
                use_cache=not no_cache,
            )

        if not products:
            display.print_warning("Nenhum produto encontrado.")
            return []

        listings: list[ProductListing]
        if cep:
            with console.status(f"[cyan]Calculando frete para CEP {cep}…[/cyan]"):
                tasks = [scraper.get_shipping(p, cep, use_cache=not no_cache) for p in products]
                listings = await asyncio.gather(*tasks)  # type: ignore[assignment]
        else:
            listings = [ProductListing(product=p) for p in products]

        return _sort_listings(list(listings))
    finally:
        await scraper.close()


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Produto a pesquisar. Ex: 'notebook gamer 16gb'")],
    cep: Annotated[Optional[str], typer.Option("--cep", "-z", help="CEP de entrega (só dígitos ou com hífen)")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Número máximo de resultados", min=1, max=50)] = 10,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Ignora cache e faz nova requisição")] = False,
    min_price: Annotated[Optional[float], typer.Option("--min", help="Preço mínimo em R$")] = None,
    max_price: Annotated[Optional[float], typer.Option("--max", help="Preço máximo em R$")] = None,
    condition: Annotated[Optional[str], typer.Option("--condition", "-c", help="Condição: new | used")] = None,
    links: Annotated[bool, typer.Option("--links", "-l", help="Exibir links dos produtos ao final")] = False,
    detail: Annotated[Optional[int], typer.Option("--detail", "-d", help="Exibir detalhe do item N da lista")] = None,
):
    """
    [bold]Busca e compara preços[/bold] de um produto nos e-commerces brasileiros.

    [dim]Exemplos:[/dim]
      pesquisa-produtos search "iphone 15"
      pesquisa-produtos search "teclado mecânico" --cep 01310-100 --limit 20
      pesquisa-produtos search "monitor 4k" --min 500 --max 3000 --no-cache
    """
    if cep is None:
        cep = _cep_prompt() or None

    listings = asyncio.run(
        _run_search(query, limit, cep, no_cache, min_price, max_price, condition)
    )
    if not listings:
        raise typer.Exit(1)

    display.print_search_results(listings, query, cep)

    if detail is not None:
        idx = detail - 1
        if 0 <= idx < len(listings):
            display.print_product_detail(listings[idx])
        else:
            display.print_error(f"Item {detail} não existe na lista (total: {len(listings)}).")

    if links:
        display.print_product_links(listings)


@app.command()
def interactive():
    """
    [bold]Modo interativo[/bold] — adicione vários produtos e compare todos de uma vez.

    [dim]Digite um produto por linha. Linha vazia encerra a entrada.[/dim]
    """
    console.print(
        "[bold cyan]Modo interativo[/bold cyan] — "
        "digite um produto por linha, [bold]Enter vazio[/bold] para finalizar.\n"
    )

    queries: list[str] = []
    while True:
        query = Prompt.ask(f"[dim]Produto {len(queries)+1}[/dim]", default="", console=console)
        if not query.strip():
            break
        queries.append(query.strip())

    if not queries:
        display.print_warning("Nenhum produto informado.")
        raise typer.Exit()

    cep = _cep_prompt()

    for query in queries:
        console.rule(f"[bold]{query}[/bold]")
        listings = asyncio.run(_run_search(query, 5, cep, False, None, None, None))
        if listings:
            display.print_search_results(listings, query, cep)
        console.print()


# ---------------------------------------------------------------------------
# Sub-comandos de cache
# ---------------------------------------------------------------------------

@cache_app.command("stats")
def cache_stats():
    """Exibe estatísticas do cache local."""
    cm = CacheManager()
    display.print_cache_stats(cm.stats())


@cache_app.command("clear")
def cache_clear(
    force: Annotated[bool, typer.Option("--force", "-f", help="Não pede confirmação")] = False,
):
    """Limpa todos os dados do cache local."""
    if not force:
        ok = Confirm.ask("[yellow]Tem certeza que quer limpar o cache?[/yellow]", console=console)
        if not ok:
            raise typer.Exit()
    cm = CacheManager()
    deleted = cm.clear()
    console.print(f"[green]Cache limpo.[/green] {deleted} entradas removidas.")


# ---------------------------------------------------------------------------
# Entrypoint direto
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
