"""Configuração central do painel. Editar aqui é o único lugar necessário
para trocar altcoins ou ajustar parâmetros de ciclo."""

# ---------------------------------------------------------------- altcoins
# 'id' = identificador da CoinGecko (não é o ticker!).
# 'vs_btc' = True quando o par contra BTC é a leitura que realmente importa.
ALTCOINS = [
    {"symbol": "ETH",    "id": "ethereum",          "name": "Ethereum"},
    {"symbol": "BNB",    "id": "binancecoin",       "name": "BNB"},
    {"symbol": "SOL",    "id": "solana",            "name": "Solana"},
    {"symbol": "HYPE",   "id": "hyperliquid",       "name": "Hyperliquid"},
    {"symbol": "ZEC",    "id": "zcash",             "name": "Zcash"},
    {"symbol": "AAVE",   "id": "aave",              "name": "Aave"},
    {"symbol": "ONDO",   "id": "ondo-finance",      "name": "Ondo"},
    {"symbol": "MORPHO", "id": "morpho",            "name": "Morpho"},
    {"symbol": "AERO",   "id": "aerodrome-finance", "name": "Aerodrome"},
    {"symbol": "CFG",    "id": "centrifuge",        "name": "Centrifuge"},
    {"symbol": "EVA",    "id": "evervalue-coin",    "name": "EverValue Coin",
     "vs_btc": True,
     "note": "Lastreado em WBTC com burn vault — a leitura relevante é EVA/BTC."},
]

# ---------------------------------------------------------------- ciclo
# Halvings (data UTC) — usados para o contador de dias de ciclo.
HALVINGS = ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20"]
BLOCKS_PER_HALVING = 210_000

# Médias móveis (em dias) que o Campos e o Wedson acompanham.
MA_WINDOWS = {
    "ma200": 200,    # Múltiplo de Mayer
    "ma350": 350,    # perna do Pi Cycle
    "ma111": 111,    # perna do Pi Cycle
    "ma730": 730,    # 2Y MA — o suporte estrutural do Wedson
}

# ---------------------------------------------------------------- macro
# Símbolos da Stooq. Índices levam '^'. Buscados um a um (mais robusto).
# Se algum acender vermelho no log, veja o símbolo correto em stooq.com.
STOOQ_SYMBOLS = {
    "^spx":  "S&P 500",
    "^ndq":  "Nasdaq 100",
    "^dji":  "Dow Jones",
    "dx.f":  "DXY (Dólar)",
    "xauusd": "Ouro",
    "10usy.b": "Treasury 10 anos",
}

# ---------------------------------------------------------------- gráfico
# Linhas de suporte on-chain que o Campos traça À MÃO (não têm fonte grátis).
# Quando ele divulgar novos valores numa live, edite os números aqui.
# Deixe value como None para a linha não aparecer.
# 'color' é opcional (usa a paleta padrão se omitido).
MANUAL_CHART_LINES = [
    {"key": "gcc",      "label": "Preço Realizado Geral (GCC)", "value": None},
    {"key": "cvdd",     "label": "CVDD",                        "value": None},
    {"key": "balanced", "label": "Balanced Price",             "value": None},
    {"key": "lth",      "label": "LTH Realized Price",          "value": None},
]

# ---------------------------------------------------------------- endpoints
CBBI_URL       = "https://colintalkscrypto.com/cbbi/data/latest.json"
CG_BASE        = "https://api.coingecko.com/api/v3"
# OKX no lugar da Binance: a Binance bloqueia servidores dos EUA (erro 451),
# que é onde o GitHub Actions roda. A OKX permite acesso público dos EUA.
OKX_BASE       = "https://www.okx.com/api/v5"
FNG_URL        = "https://api.alternative.me/fng/?limit=2"
MEMPOOL_BASE   = "https://mempool.space/api"
STOOQ_BASE     = "https://stooq.com/q/l/"
# CoinMarketCap API pública SEM CHAVE (prefixo /public-api). Traz o Altcoin
# Season Index oficial. Se falhar, calculamos um índice próprio das altcoins.
CMC_PUBLIC     = "https://pro-api.coinmarketcap.com/public-api"

# ---------------------------------------------------------------- ETF
# Fluxos de ETF via Farside Investors (farside.co.uk). Eles servem a tabela em
# HTML puro, então lemos e extraímos (scraping). É mais frágil que uma API: se
# a Farside mudar o layout, a extração para e o bloco fica vazio com aviso —
# mas nada mais no painel quebra (fonte isolada, como todas as outras).
ETF_ENABLED = True
# WalletPilot: fonte principal do BTC. Entrega 1D/7D/30D já agregados e NÃO
# bloqueia leitura (diferente da Farside, que fica atrás do Cloudflare).
# Cobre só Bitcoin. Para ETH/SOL/HYPE tentamos a Farside via proxy.
ETF_WALLETPILOT = "https://www.walletpilot.com/bitcoin-tracker/etfs"
ETF_SOURCES = {
    "ETH":  "https://farside.co.uk/eth/",
    "SOL":  "https://farside.co.uk/sol/",
    "HYPE": "https://farside.co.uk/hyp/",
}

HTTP_TIMEOUT = 25
USER_AGENT = "btc-cockpit/1.0 (painel pessoal de acompanhamento)"

# Rótulos amigáveis para as métricas que vêm do CBBI.
# As chaves do JSON do CBBI são casadas de forma tolerante (case-insensitive,
# ignorando espaços/underscores), então pequenas mudanças de nome não quebram.
CBBI_LABELS = {
    "confidence":   "CBBI (confiança de topo)",
    "picycle":      "Pi Cycle Top",
    "mvrv":         "MVRV Z-Score",
    "puell":        "Múltiplo de Puell",
    "rupl":         "NUPL / RUPL",
    "rhodl":        "RHODL Ratio",
    "2yma":         "Média Móvel 2 Anos",
    "reserverisk":  "Reserve Risk",
    "trolololo":    "Trolololo Trend Line",
    "woobull":      "Top Cap vs CVDD",
}
