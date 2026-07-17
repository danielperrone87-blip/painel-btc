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
# Símbolos da Stooq. Alguns podem não resolver — o script degrada sem quebrar
# e reporta em 'sources'. Ajustar aqui se o log acusar falha.
STOOQ_SYMBOLS = {
    "^spx":    "S&P 500",
    "^ndq":    "Nasdaq 100",
    "dx.f":    "DXY (Dólar)",
    "xauusd":  "Ouro",
    "10usy.b": "Treasury 10 anos",
}

# ---------------------------------------------------------------- endpoints
CBBI_URL       = "https://colintalkscrypto.com/cbbi/data/latest.json"
CG_BASE        = "https://api.coingecko.com/api/v3"
BINANCE_SPOT   = "https://api.binance.com/api/v3"
BINANCE_FUT    = "https://fapi.binance.com/fapi/v1"
FNG_URL        = "https://api.alternative.me/fng/?limit=2"
MEMPOOL_BASE   = "https://mempool.space/api"
STOOQ_BASE     = "https://stooq.com/q/l/"

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
