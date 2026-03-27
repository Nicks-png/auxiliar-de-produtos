# pesquisa-produtos

Assistente de compras inteligente via CLI. Compara preços, calcula frete e destaca promoções em e-commerces brasileiros.

## Funcionalidades

- Busca de produtos no **Mercado Livre** via API pública
- Cálculo de frete por CEP com estimativa de prazo
- Tabela comparativa: Loja · Preço · Frete · Prazo · Total · Promoção
- Cache local SQLite (evita requisições repetidas)
- Rate limiting automático (respeita limites da API)
- Modo interativo para comparar múltiplos produtos

## Pré-requisitos

- Python 3.11+
- pip

## Instalação

```bash
# Clone o repositório
git clone https://github.com/Nicks-png/auxiliar-de-produtos.git
cd auxiliar-de-produtos

# Crie e ative um virtualenv
python -m venv .venv
.venv\Scripts\activate       # Windows
# ou: source .venv/bin/activate  # Linux/Mac

# Instale o pacote
pip install -e .

# Copie e configure o .env (opcional — aumenta rate limit da ML API)
copy .env.example .env
```

## Uso

```bash
# Busca simples
pesquisa-produtos search "notebook gamer"

# Com CEP para calcular frete
pesquisa-produtos search "iphone 15" --cep 01310-100

# Filtrar por preço e ver links
pesquisa-produtos search "monitor 4k" --min 800 --max 3000 --links

# Produtos usados, top 20 resultados
pesquisa-produtos search "ps5" --condition used --limit 20

# Ver detalhe do 1º item
pesquisa-produtos search "teclado mecânico" --cep 01310-100 --detail 1

# Modo interativo (múltiplos produtos de uma vez)
pesquisa-produtos interactive

# Cache
pesquisa-produtos cache stats
pesquisa-produtos cache clear
```

## Estrutura

```
pesquisa_produtos/
├── cli/
│   └── commands.py      # Comandos Typer
├── scrapers/
│   ├── base.py          # Classe base (httpx + cache + rate limit)
│   └── mercadolivre.py  # API pública do Mercado Livre
├── models/
│   └── product.py       # Product, ShippingOption, ProductListing
└── utils/
    ├── cache.py         # Cache SQLite com TTL
    ├── rate_limiter.py  # Token bucket
    └── display.py       # Tabelas Rich
```

## Variáveis de ambiente (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `ML_ACCESS_TOKEN` | — | Token ML (opcional, aumenta rate limit) |
| `CACHE_TTL_SECONDS` | `3600` | Validade do cache em segundos |
| `CACHE_DIR` | `data` | Diretório do banco SQLite |
