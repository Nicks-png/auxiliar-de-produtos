"""Toda a renderização Rich está aqui. CLI não imprime nada diretamente."""
from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from pesquisa_produtos.models.product import Product, ProductListing, ShippingOption

console = Console()


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def print_search_results(listings: list[ProductListing], query: str, cep: Optional[str] = None) -> None:
    """Tabela comparativa principal: Loja | Preço | Frete | Prazo | Total | Promoção."""
    title = f"[bold cyan]Resultados para:[/bold cyan] [white]{query}[/white]"
    if cep:
        title += f"  [dim]· CEP {cep}[/dim]"

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_lines=True,
        highlight=True,
        title_justify="left",
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Produto", min_width=35, max_width=48, no_wrap=False)
    table.add_column("Loja", style="cyan", width=14)
    table.add_column("Preço", style="green bold", justify="right", width=12)
    table.add_column("Frete", justify="right", width=12)
    table.add_column("Prazo", justify="center", width=10)
    table.add_column("Total", style="bold", justify="right", width=12)
    table.add_column("Promoção", width=16)

    for i, listing in enumerate(listings, 1):
        p = listing.product
        ship = listing.cheapest_shipping

        frete_str = _shipping_cell(p, ship)
        prazo_str = ship.display_days if ship else ("—" if not p.free_shipping else "—")
        promo_str = _promo_cell(p)
        total_color = "bold green" if i == 1 else "bold"

        table.add_row(
            str(i),
            _truncate(p.title, 48),
            p.store,
            p.price_brl,
            frete_str,
            prazo_str,
            f"[{total_color}]{listing.total_brl}[/{total_color}]",
            promo_str,
        )

    console.print(table)

    # Legenda
    console.print(
        "[dim]* Ordenado por menor total (preço + frete). "
        "Acesse os links para confirmar valores no site.[/dim]\n"
    )


def _shipping_cell(product: Product, ship: Optional[ShippingOption]) -> str:
    if ship:
        if ship.is_free or ship.cost == 0:
            return "[green]Grátis[/green]"
        return f"R$ {ship.cost:.2f}"
    if product.free_shipping:
        return "[green]Grátis[/green]"
    return "[dim]A consultar[/dim]"


def _promo_cell(product: Product) -> str:
    if not product.promotion:
        return ""
    if "Relâmpago" in product.promotion:
        return f"[yellow]{product.promotion}[/yellow]"
    return f"[magenta]{product.promotion}[/magenta]"


def print_product_detail(listing: ProductListing) -> None:
    p = listing.product
    info = Table(box=None, show_header=False, padding=(0, 2))
    info.add_column("Campo", style="dim", width=16)
    info.add_column("Valor")

    info.add_row("Título", p.title)
    info.add_row("Loja", p.store)
    info.add_row("Preço", f"[green bold]{p.price_brl}[/green bold]")
    info.add_row("Condição", p.condition_label)
    info.add_row("Vendedor", p.seller or "—")
    info.add_row("Frete grátis", "Sim" if p.free_shipping else "Não")
    info.add_row("Promoção", p.promotion or "—")
    info.add_row("Em estoque", str(p.available_quantity))
    info.add_row("Link", f"[link={p.url}]{p.url[:70]}…[/link]" if len(p.url) > 70 else p.url)
    info.add_row("Capturado em", p.scraped_at.strftime("%d/%m/%Y %H:%M"))

    if listing.shipping_options:
        rows = []
        for s in listing.shipping_options:
            rows.append(f"  {s.method}: {s.display_cost} · {s.display_days}")
        info.add_row("Opções frete", "\n".join(rows))

    panel = Panel(info, title=f"[bold]{_truncate(p.title, 60)}[/bold]", border_style="cyan")
    console.print(panel)


def print_product_links(listings: list[ProductListing]) -> None:
    console.print("\n[bold]Links dos produtos:[/bold]")
    for i, listing in enumerate(listings, 1):
        console.print(f"  [dim]{i}.[/dim] {listing.product.url}")


def print_cache_stats(stats: dict) -> None:
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Métrica", style="dim")
    table.add_column("Valor", style="cyan")
    for k, v in stats.items():
        table.add_row(k, str(v))
    console.print(Panel(table, title="[bold]Cache[/bold]", border_style="dim"))


def print_error(message: str) -> None:
    console.print(f"[bold red]Erro:[/bold red] {message}")


def print_warning(message: str) -> None:
    console.print(f"[yellow]Aviso:[/yellow] {message}")


def print_info(message: str) -> None:
    console.print(f"[dim]{message}[/dim]")
