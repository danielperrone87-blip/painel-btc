#!/usr/bin/env python3
"""
Monta o data.json que alimenta o painel.

Roda no GitHub Actions (lado servidor), não no navegador. Isso resolve CORS,
protege chaves e ainda deixa um histórico versionado de brinde.

Regra de ouro: NENHUMA fonte pode derrubar o build. Cada uma é isolada; se
falhar, o campo vira null e o motivo aparece em data['sources'], que o painel
mostra na faixa de saúde das fontes. Melhor um card vazio e honesto do que um
número inventado.
"""

import csv
import io
import json
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import (  # noqa: E402
    ALTCOINS, HALVINGS, BLOCKS_PER_HALVING, MA_WINDOWS, STOOQ_SYMBOLS,
    CBBI_URL, CG_BASE, OKX_BASE, FNG_URL, MEMPOOL_BASE, STOOQ_BASE,
    CMC_PUBLIC, HTTP_TIMEOUT, USER_AGENT, CBBI_LABELS, MANUAL_CHART_LINES,
    ETF_ENABLED, ETF_SOURCES, ETF_WALLETPILOT,
)

ROOT = Path(__file__).parent.parent
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

SOURCES = {}  # nome -> {"ok": bool, "detail": str}


def source(name):
    """Isola uma fonte: retorna None em vez de explodir, e registra o status."""
    def wrap(fn):
        def inner(*args, **kwargs):
            try:
                out = fn(*args, **kwargs)
                SOURCES[name] = {"ok": True, "detail": "ok"}
                return out
            except Exception as exc:  # noqa: BLE001
                SOURCES[name] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
                print(f"[falha] {name}: {exc}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return None
        return inner
    return wrap


def get_json(url, **kw):
    r = SESSION.get(url, timeout=HTTP_TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------- CBBI

def _norm(k):
    return "".join(c for c in k.lower() if c.isalnum())


@source("CBBI")
def fetch_cbbi():
    """Uma chamada gratuita traz Pi Cycle, MVRV-Z, Puell, NUPL, RHODL, 2Y MA,
    Reserve Risk, Trolololo, Top Cap vs CVDD, o score de confiança e a série
    completa de preço desde 2011."""
    raw = get_json(CBBI_URL)

    def latest(series):
        if not isinstance(series, dict) or not series:
            return None, None
        ts = max(series.keys(), key=int)
        val = series[ts]
        return (None, None) if val is None else (float(val), int(ts))

    metrics = {}
    for key, series in raw.items():
        norm = _norm(key)
        if norm == "price":
            continue
        val, ts = latest(series)
        if val is None:
            continue
        # CBBI entrega 0..1; normalizamos para 0..100 (escala do site).
        score = val * 100 if 0 <= val <= 1 else val
        metrics[norm] = {
            "label": CBBI_LABELS.get(norm, key),
            "score": round(score, 1),
            "as_of": ts,
        }

    price_series = {}
    for k, v in (raw.get("Price") or {}).items():
        if v is not None:
            price_series[int(k)] = float(v)

    return {"metrics": metrics, "price_series": price_series}


# ------------------------------------------------------- modelos de preço

def price_models(price_series, live_price):
    """Tudo aqui sai só do preço — zero dependência externa.
    Mayer, MM200, múltiplo da 2Y MA, Pi Cycle, drawdown do topo."""
    if not price_series:
        return None

    ordered = [price_series[k] for k in sorted(price_series)]
    px = live_price or ordered[-1]

    def sma(n):
        return sum(ordered[-n:]) / n if len(ordered) >= n else None

    ma200 = sma(MA_WINDOWS["ma200"])
    ma111 = sma(MA_WINDOWS["ma111"])
    ma350 = sma(MA_WINDOWS["ma350"])
    ma730 = sma(MA_WINDOWS["ma730"])

    ath = max(ordered + [px])
    pi_top = ma350 * 2 if ma350 else None

    out = {
        "price": px,
        "ath": ath,
        "drawdown_from_ath": (px / ath - 1) * 100 if ath else None,
        "ma200": ma200,
        "mayer_multiple": px / ma200 if ma200 else None,
        "ma730": ma730,
        "ma730_multiple": px / ma730 if ma730 else None,
        "ma111": ma111,
        "pi_cycle_top_line": pi_top,
        # >= 0 significa que a 111DMA cruzou acima da 350DMA x2 (sinal de topo).
        "pi_cycle_gap_pct": (ma111 / pi_top - 1) * 100 if (ma111 and pi_top) else None,
    }

    # Retorno no ano corrente
    now = datetime.now(timezone.utc)
    jan1 = int(datetime(now.year, 1, 1, tzinfo=timezone.utc).timestamp())
    prior = [v for k, v in sorted(price_series.items()) if k <= jan1]
    if prior:
        out["ytd_pct"] = (px / prior[-1] - 1) * 100

    # Stochastic RSI (diário) — sobrecompra/sobrevenda.
    out["stoch_rsi"] = stoch_rsi(ordered)

    return out


def _rsi(values, period=14):
    """RSI clássico (Wilder). Retorna a série de RSI alinhada ao fim."""
    if len(values) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    # média inicial
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    rsis = []
    for i in range(period, len(gains) + 1):
        if i > period:
            avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
            avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        rs = (avg_g / avg_l) if avg_l else float("inf")
        rsis.append(100 - 100 / (1 + rs))
    return rsis


def stoch_rsi(prices, rsi_period=14, stoch_period=14):
    """Stochastic RSI: onde o RSI está dentro da sua própria faixa recente.
    0-100. <20 = sobrevendido, >80 = sobrecomprado. Leitura de momentum."""
    rsis = _rsi(prices, rsi_period)
    if len(rsis) < stoch_period:
        return None
    window = rsis[-stoch_period:]
    lo, hi = min(window), max(window)
    cur = rsis[-1]
    k = (cur - lo) / (hi - lo) * 100 if hi > lo else 50.0
    if k < 20:
        zona = "sobrevendido"
    elif k > 80:
        zona = "sobrecomprado"
    else:
        zona = "neutro"
    return {"value": round(k, 1), "rsi": round(cur, 1), "zone": zona}


def build_chart_series(price_series, cbbi_metrics, manual_lines):
    """Série semanal para o gráfico do BTC com as linhas de ciclo traçadas.

    Automáticas (calculadas do preço): SMA 200/300/400 semanal, MVRV 0.80.
    Do CBBI: CVDD (via Top Cap vs CVDD, quando disponível).
    Manuais (Daniel digita em config): GCC, Balanced Price, LTH Realized Price.

    Salvo à parte do data.json porque é maior e muda devagar — não precisa
    recarregar a cada abertura do painel."""
    if not price_series:
        return None

    items = sorted(price_series.items())            # (ts, preço) diário
    ordered = [v for _, v in items]

    def sma_at(idx, days):
        """Média dos 'days' dias até idx (inclusive)."""
        if idx + 1 < days:
            return None
        janela = ordered[idx + 1 - days: idx + 1]
        return sum(janela) / len(janela)

    W = 7  # passo semanal (reduz ~7x o tamanho do arquivo)
    D200, D300, D400 = 200 * 7, 300 * 7, 400 * 7    # semanas -> dias

    points = []
    for i in range(0, len(items), W):
        ts, px = items[i]
        points.append({
            "t": ts * 1000,                          # ms, formato do gráfico
            "price": round(px, 2),
            "sma200w": round(sma_at(i, D200), 2) if sma_at(i, D200) else None,
            "sma300w": round(sma_at(i, D300), 2) if sma_at(i, D300) else None,
            "sma400w": round(sma_at(i, D400), 2) if sma_at(i, D400) else None,
        })

    # Sempre inclui o último ponto real (o loop pode pular ele)
    ts_last, px_last = items[-1]
    if points and points[-1]["t"] != ts_last * 1000:
        j = len(items) - 1
        points.append({
            "t": ts_last * 1000, "price": round(px_last, 2),
            "sma200w": round(sma_at(j, D200), 2) if sma_at(j, D200) else None,
            "sma300w": round(sma_at(j, D300), 2) if sma_at(j, D300) else None,
            "sma400w": round(sma_at(j, D400), 2) if sma_at(j, D400) else None,
        })

    # MVRV 0.80: aproximação da linha de suporte que o Campos traça.
    # Realized Price ~ preço / MVRV atual; a 0.80 marca 80% desse valor.
    # Sem realized price on-chain grátis, usamos a SMA de ~200 dias como proxy
    # do custo médio e aplicamos o fator — é uma APROXIMAÇÃO, rotulada como tal.
    mvrv080 = None
    proxy_realized = sma_at(len(items) - 1, 200)
    if proxy_realized:
        mvrv080 = round(proxy_realized * 0.80, 2)

    return {
        "points": points,
        "auto_levels": {
            "mvrv080": {"label": "MVRV 0,80 (aprox.)", "value": mvrv080},
        },
        "manual_levels": manual_lines,   # vem do config, Daniel edita
        "last_price": round(px_last, 2),
    }


def cycle_clock(block_height):
    """Onde estamos no ciclo do halving."""
    now = datetime.now(timezone.utc)
    last = datetime.fromisoformat(HALVINGS[-1]).replace(tzinfo=timezone.utc)
    out = {
        "last_halving": HALVINGS[-1],
        "days_since_halving": (now - last).days,
    }
    if block_height:
        nxt = (block_height // BLOCKS_PER_HALVING + 1) * BLOCKS_PER_HALVING
        blocks_left = nxt - block_height
        out["next_halving_block"] = nxt
        out["blocks_to_halving"] = blocks_left
        # ~10 min por bloco
        out["est_next_halving"] = (
            now + timedelta(minutes=10 * blocks_left)
        ).strftime("%Y-%m-%d")
    return out


# ---------------------------------------------------------------- mercado

@source("CoinGecko")
def fetch_coingecko():
    ids = ["bitcoin"] + [a["id"] for a in ALTCOINS]
    common = {
        "vs_currency": "usd",
        "ids": ",".join(ids),
        "price_change_percentage": "24h,7d,30d,1y",
        "per_page": 250,
    }
    usd = get_json(f"{CG_BASE}/coins/markets", params=common)

    btc = get_json(f"{CG_BASE}/coins/markets", params={
        **common, "vs_currency": "btc", "price_change_percentage": "7d,30d",
    })

    glob = get_json(f"{CG_BASE}/global")["data"]

    by_id_usd = {c["id"]: c for c in usd}
    by_id_btc = {c["id"]: c for c in btc}

    def pack(meta):
        u = by_id_usd.get(meta["id"])
        b = by_id_btc.get(meta["id"])
        if not u:
            return {**meta, "missing": True}
        return {
            "symbol": meta["symbol"],
            "name": meta["name"],
            "note": meta.get("note"),
            "vs_btc_focus": bool(meta.get("vs_btc")),
            "price": u.get("current_price"),
            "mcap": u.get("market_cap"),
            "chg24h": u.get("price_change_percentage_24h_in_currency"),
            "chg7d": u.get("price_change_percentage_7d_in_currency"),
            "chg30d": u.get("price_change_percentage_30d_in_currency"),
            "chg1y": u.get("price_change_percentage_1y_in_currency"),
            "price_btc": (b or {}).get("current_price"),
            "chg7d_btc": (b or {}).get("price_change_percentage_7d_in_currency"),
            "chg30d_btc": (b or {}).get("price_change_percentage_30d_in_currency"),
        }

    btc_row = by_id_usd.get("bitcoin", {})
    return {
        "btc": {
            "price": btc_row.get("current_price"),
            "chg24h": btc_row.get("price_change_percentage_24h_in_currency"),
            "chg7d": btc_row.get("price_change_percentage_7d_in_currency"),
            "chg30d": btc_row.get("price_change_percentage_30d_in_currency"),
            "chg1y": btc_row.get("price_change_percentage_1y_in_currency"),
            "mcap": btc_row.get("market_cap"),
        },
        "alts": [pack(a) for a in ALTCOINS],
        "dominance": {
            "btc": glob["market_cap_percentage"].get("btc"),
            "eth": glob["market_cap_percentage"].get("eth"),
        },
        "total_mcap": glob["total_market_cap"].get("usd"),
        "total_mcap_chg24h": glob.get("market_cap_change_percentage_24h_usd"),
    }


@source("OKX (derivativos)")
def fetch_derivatives():
    """Funding e open interest via OKX. Trocamos a Binance porque ela devolve
    451 (bloqueio geográfico) quando chamada de servidores dos EUA, que é onde
    o GitHub Actions roda. A OKX mantém acesso público dos EUA e não pede chave."""
    inst = "BTC-USDT-SWAP"

    def first(js):
        return (js.get("data") or [{}])[0]

    fr = first(get_json(f"{OKX_BASE}/public/funding-rate", params={"instId": inst}))
    oi = first(get_json(f"{OKX_BASE}/public/open-interest",
                        params={"instType": "SWAP", "instId": inst}))
    mk = first(get_json(f"{OKX_BASE}/public/mark-price",
                        params={"instType": "SWAP", "instId": inst}))

    def num(d, k):
        v = d.get(k)
        return float(v) if v not in (None, "") else None

    mark = num(mk, "markPx")
    contracts = num(oi, "oiCcy")          # OI em BTC
    oi_usd = num(oi, "oiUsd")             # OKX já costuma entregar em USD
    if oi_usd is None and contracts and mark:
        oi_usd = contracts * mark

    funding = num(fr, "fundingRate")
    return {
        "funding_rate_pct": funding * 100 if funding is not None else None,
        "next_funding": fr.get("nextFundingTime") or None,
        "open_interest_btc": contracts,
        "open_interest_usd": oi_usd,
        "mark_price": mark,
    }


@source("Fear & Greed")
def fetch_fng():
    d = get_json(FNG_URL)["data"]
    cur = d[0]
    prev = d[1] if len(d) > 1 else None
    return {
        "value": int(cur["value"]),
        "label": cur["value_classification"],
        "previous": int(prev["value"]) if prev else None,
    }


@source("Altcoin Season (CMC)")
def fetch_altseason(alts):
    """Altcoin Season Index oficial via API keyless da CoinMarketCap.
    Se a CMC falhar, calcula um índice próprio: % das alts da watchlist
    que superaram o BTC em 30 dias (mesma ideia, escopo menor)."""
    try:
        js = get_json(f"{CMC_PUBLIC}/v1/altcoin-season-index/latest")
        idx = (js.get("data") or {}).get("altcoin_index")
        if idx is not None:
            return {"value": round(float(idx), 0), "source": "CMC (top 100)",
                    "note": "0-25 temporada do BTC · 75-100 temporada de alts"}
    except Exception:
        pass  # cai no cálculo próprio

    # Fallback: das minhas alts, quantas ganharam do BTC em 30d?
    vals = [a.get("chg30d_btc") for a in (alts or [])
            if not a.get("missing") and a.get("chg30d_btc") is not None]
    if not vals:
        raise RuntimeError("sem CMC e sem dados de alts para calcular")
    outperf = sum(1 for v in vals if v > 0)
    pct = round(outperf / len(vals) * 100, 0)
    return {"value": pct, "source": f"próprio ({len(vals)} alts)",
            "note": "% da sua watchlist que superou o BTC em 30d"}


@source("mempool.space")
def fetch_network():
    diff = get_json(f"{MEMPOOL_BASE}/v1/difficulty-adjustment")
    fees = get_json(f"{MEMPOOL_BASE}/v1/fees/recommended")
    hr = get_json(f"{MEMPOOL_BASE}/v1/mining/hashrate/3d")
    height = SESSION.get(f"{MEMPOOL_BASE}/blocks/tip/height", timeout=HTTP_TIMEOUT)
    height.raise_for_status()
    return {
        "block_height": int(height.text.strip()),
        "hashrate": hr.get("currentHashrate"),
        "difficulty": hr.get("currentDifficulty"),
        "difficulty_change_pct": diff.get("difficultyChange"),
        "blocks_to_retarget": diff.get("remainingBlocks"),
        "fee_fast": fees.get("fastestFee"),
        "fee_economy": fees.get("economyFee"),
    }


@source("Stooq (macro)")
def fetch_macro():
    """Índices macro da Stooq. A Stooq bloqueia o IP do GitHub Actions, então
    buscamos via proxy (CodeTabs), um símbolo por vez. Se um símbolo falhar,
    os outros ainda vêm."""
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    out = []
    falhas = []
    for sym, label in STOOQ_SYMBOLS.items():
        # URL da Stooq para um símbolo em CSV
        base = f"{STOOQ_BASE}?s={sym}&f=sd2t2ohlcv&h&e=csv"
        texto = None
        # tenta direto e, se falhar, via proxy
        for alvo in (base, "https://api.codetabs.com/v1/proxy/?quest=" + base):
            try:
                r = SESSION.get(alvo, timeout=HTTP_TIMEOUT + 10,
                                headers={"User-Agent": ua})
                r.raise_for_status()
                if "Date" in r.text or "," in r.text:
                    texto = r.text
                    break
            except Exception:  # noqa: BLE001
                continue
        if not texto:
            falhas.append(sym); continue
        try:
            rows = list(csv.DictReader(io.StringIO(texto)))
            if not rows:
                falhas.append(sym); continue
            row = rows[0]
            close = row.get("Close"); openp = row.get("Open")
            if close in (None, "", "N/D") or openp in (None, "", "N/D"):
                falhas.append(sym); continue
            close = float(close); openp = float(openp)
            out.append({
                "symbol": sym, "label": label, "close": close,
                "chg_pct": (close / openp - 1) * 100 if openp else None,
                "date": row.get("Date"),
            })
        except Exception:  # noqa: BLE001
            falhas.append(sym)
    if not out:
        raise RuntimeError("Stooq: nenhum símbolo válido (" + ",".join(falhas) + ")")
    return out


# --------------------------------------------------------------- ETF flows

def _etf_num(s):
    """Formato britânico da Farside: '(300.4)' -> -300.4, '1,255' -> 1255, '-' -> None."""
    s = (s or "").strip()
    if s in ("-", "", "–", "—"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace(" ", "")
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _parse_farside(html):
    """Extrai (data, total_diário) de cada linha e o total histórico da tabela.
    A Farside serve HTML; procuramos linhas de tabela com data e a última coluna
    (Total). Tolerante a <td>...</td> ou a texto separado por '|'."""
    import re as _re
    # Normaliza: transforma células HTML em separadores '|'
    txt = _re.sub(r"</t[dh]>", "|", html)
    txt = _re.sub(r"<[^>]+>", "", txt)             # remove tags restantes
    txt = txt.replace("&nbsp;", " ")

    daily = []
    hist_total = None
    for line in txt.splitlines():
        cells = [c.strip() for c in line.split("|") if c.strip() != ""]
        if len(cells) < 2:
            continue
        head = cells[0]
        if _re.match(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$", head):
            try:
                dt = datetime.strptime(head, "%d %b %Y").date()
            except ValueError:
                continue
            daily.append((dt, _etf_num(cells[-1])))
        elif head.lower() == "total":
            hist_total = _etf_num(cells[-1])
    return daily, hist_total


def _etf_summary(daily, hist_total):
    real = [(d, t) for d, t in daily if t is not None]
    # remove dias em aberto no fim (total 0 sem fluxo lançado)
    while real and real[-1][1] == 0.0:
        real.pop()
    if not real:
        return None
    last_dt, last_val = real[-1]
    return {
        "last_day": round(last_val, 1),
        "last_date": last_dt.isoformat(),
        "week": round(sum(t for _, t in real[-5:]), 1),      # ~5 pregões
        "month": round(sum(t for _, t in real[-21:]), 1),    # ~21 pregões
        "cumulative": round(hist_total, 0) if hist_total is not None else None,
        "unit": "US$ mi",
    }


def _parse_walletpilot(text):
    """Extrai o Total (1D, 7D, 30D em US$mi) da WalletPilot. A linha 'Total'
    da tabela markdown tem os três agregados já prontos."""
    def money(s):
        s = s.strip().replace("$", "").replace(",", "").replace("M", "")
        s = s.replace("B", "").replace("+", "")
        if s in ("", "—", "-"):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    for line in text.splitlines():
        if "**Total**" in line or "| Total " in line:
            cells = [c.strip() for c in line.split("|")]
            nums = [money(c) for c in cells if "$" in c and "M" in c]
            if len(nums) >= 3:
                # cumulativo histórico não vem nessa linha; deixamos None
                return {"last_day": nums[0], "last_date": None,
                        "week": nums[1], "month": nums[2],
                        "cumulative": None, "unit": "US$ mi"}
    return None


@source("ETF (BTC via WalletPilot)")
def fetch_etf_btc():
    """Fluxo do ETF de Bitcoin via WalletPilot — fonte que não bloqueia e já
    entrega 1D/7D/30D prontos."""
    if not ETF_ENABLED:
        raise RuntimeError("ETF desativado")
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
    r = SESSION.get(ETF_WALLETPILOT, timeout=HTTP_TIMEOUT + 10,
                    headers={"User-Agent": ua})
    r.raise_for_status()
    summ = _parse_walletpilot(r.text)
    if not summ:
        raise RuntimeError("WalletPilot: linha Total não encontrada")
    return summ


@source("ETF alts (Farside)")
def fetch_etf_flows():
    """Fluxos de ETF (BTC, ETH, SOL, HYPE) da Farside Investors.
    A Farside fica atrás do Cloudflare, que bloqueia o IP do GitHub Actions.
    Tentamos, em cascata: (1) direto, (2) proxy CodeTabs, (3) proxy AllOrigins.
    Basta um funcionar. Cada ativo é isolado."""
    if not ETF_ENABLED:
        raise RuntimeError("ETF desativado em config (ETF_ENABLED=False)")
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

    def vias(url):
        # Ordem de tentativa. Proxies que buscam a página do lado servidor e
        # devolvem o HTML/texto, contornando o bloqueio do Cloudflare.
        from urllib.parse import quote
        yield url, {"User-Agent": ua, "Accept": "text/html"}
        yield "https://api.codetabs.com/v1/proxy/?quest=" + url, {"User-Agent": ua}
        yield "https://api.allorigins.win/raw?url=" + quote(url, safe=""), {"User-Agent": ua}

    def buscar(url):
        ultimo_erro = None
        for alvo, headers in vias(url):
            try:
                r = SESSION.get(alvo, timeout=HTTP_TIMEOUT + 15, headers=headers)
                r.raise_for_status()
                daily, hist = _parse_farside(r.text)
                if daily:
                    return daily, hist
                ultimo_erro = "sem linhas"
            except Exception as exc:  # noqa: BLE001
                ultimo_erro = type(exc).__name__
        raise RuntimeError(ultimo_erro or "falhou")

    out = {}
    erros = []
    for asset, url in ETF_SOURCES.items():
        try:
            daily, hist = buscar(url)
            summ = _etf_summary(daily, hist)
            if summ:
                out[asset] = summ
            else:
                erros.append(f"{asset}: sem dados")
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{asset}: {exc}")
    if not out:
        raise RuntimeError("nenhum ETF extraído — " + "; ".join(erros))
    return out


# ------------------------------------------------------------- insights

def build_insights(cbbi, models, derivs, fng, market, altseason):
    """Lê o conjunto de métricas e DESCREVE o momento — sem recomendar
    compra ou venda. Cada frase aponta o que o dado indica historicamente.
    O objetivo é síntese, não conselho: mostra convergências e divergências."""
    obs = []

    def score(k):
        m = (cbbi or {}).get(k)
        return m["score"] if m and m.get("score") is not None else None

    conf = score("confidence")

    # --- posição de ciclo (CBBI)
    if conf is not None:
        if conf >= 85:
            obs.append(("ciclo", "quente",
                "CBBI em {:.0f}/100 — zona de euforia. Historicamente é a "
                "faixa em que ciclos anteriores formaram topos.".format(conf)))
        elif conf >= 70:
            obs.append(("ciclo", "quente",
                "CBBI em {:.0f}/100 — faixa aquecida, mas ainda não extrema.".format(conf)))
        elif conf < 25:
            obs.append(("ciclo", "frio",
                "CBBI em {:.0f}/100 — zona historicamente fria, associada a "
                "fundos de ciclo.".format(conf)))
        else:
            obs.append(("ciclo", "neutro",
                "CBBI em {:.0f}/100 — meio da faixa, sem extremo de ciclo.".format(conf)))

    # --- preço vs médias
    mm = (models or {}).get("mayer_multiple")
    if mm is not None:
        if mm < 1:
            obs.append(("preço", "frio",
                "Múltiplo de Mayer em {:.2f} (<1): preço abaixo da média de "
                "200 dias, território historicamente barato.".format(mm)))
        elif mm > 2.4:
            obs.append(("preço", "quente",
                "Múltiplo de Mayer em {:.2f} (>2,4): preço muito esticado "
                "acima da média de 200 dias.".format(mm)))

    # --- Pi Cycle
    pi = (models or {}).get("pi_cycle_gap_pct")
    if pi is not None and pi >= -5:
        obs.append(("preço", "quente",
            "Pi Cycle a {:.0f}% do cruzamento — sinal clássico de proximidade "
            "de topo quando a 111DMA alcança a 350DMA×2.".format(pi)
            if pi < 0 else
            "Pi Cycle CRUZOU — em ciclos passados coincidiu com topos."))

    # --- Stoch RSI
    sr = (models or {}).get("stoch_rsi")
    if sr:
        if sr["zone"] == "sobrevendido":
            obs.append(("momentum", "frio",
                "Stoch RSI em {:.0f} (sobrevendido): momentum esticado para "
                "baixo no curto prazo.".format(sr["value"])))
        elif sr["zone"] == "sobrecomprado":
            obs.append(("momentum", "quente",
                "Stoch RSI em {:.0f} (sobrecomprado): momentum esticado para "
                "cima no curto prazo.".format(sr["value"])))

    # --- derivativos
    fr = (derivs or {}).get("funding_rate_pct")
    if fr is not None:
        if fr > 0.03:
            obs.append(("risco", "quente",
                "Funding em {:.3f}% — comprados pagando caro para manter "
                "posição, sinal de alavancagem otimista elevada.".format(fr)))
        elif fr < 0:
            obs.append(("risco", "frio",
                "Funding negativo ({:.3f}%) — vendidos pagando, indicando "
                "pessimismo no mercado alavancado.".format(fr)))

    # --- medo e ganância
    fgv = (fng or {}).get("value")
    if fgv is not None:
        if fgv >= 75:
            obs.append(("sentimento", "quente",
                "Medo & Ganância em {} (ganância) — sentimento aquecido.".format(fgv)))
        elif fgv <= 25:
            obs.append(("sentimento", "frio",
                "Medo & Ganância em {} (medo) — sentimento deprimido.".format(fgv)))

    # --- altseason
    asv = (altseason or {}).get("value")
    if asv is not None:
        if asv >= 75:
            obs.append(("alts", "info",
                "Altcoin Season em {:.0f} — alts amplamente superando o BTC.".format(asv)))
        elif asv <= 25:
            obs.append(("alts", "info",
                "Altcoin Season em {:.0f} — capital concentrado no BTC.".format(asv)))

    # --- síntese: contar temperatura
    quentes = sum(1 for _, t, _ in obs if t == "quente")
    frios = sum(1 for _, t, _ in obs if t == "frio")
    if quentes and quentes >= frios + 2:
        resumo = ("Vários indicadores de ciclo e risco na faixa quente ao mesmo "
                  "tempo — leitura de mercado esticado. Convergência costuma "
                  "merecer mais atenção que um sinal isolado.")
    elif frios and frios >= quentes + 2:
        resumo = ("Predomínio de leituras na faixa fria — historicamente "
                  "associado a fases de acumulação, sem sinais de "
                  "sobreaquecimento no conjunto.")
    else:
        resumo = ("Sinais mistos: indicadores quentes e frios convivem. "
                  "Momentos assim pedem acompanhar qual lado ganha força.")

    return {
        "resumo": resumo,
        "observacoes": [{"tag": t, "temp": temp, "texto": txt} for t, temp, txt in obs],
        "disclaimer": "Leitura descritiva dos dados, não recomendação de compra ou venda.",
    }


# ------------------------------------------------------------------- main

def main():
    now = datetime.now(timezone.utc)

    cbbi = fetch_cbbi()
    market = fetch_coingecko()
    derivs = fetch_derivatives()
    fng = fetch_fng()
    net = fetch_network()
    macro = fetch_macro()
    altseason = fetch_altseason((market or {}).get("alts", []))
    # ETF: BTC vem da WalletPilot (confiável); ETH/SOL/HYPE da Farside (via proxy).
    etf_btc = fetch_etf_btc()
    etf_alts = fetch_etf_flows()
    etf = {}
    if etf_btc:
        etf["BTC"] = etf_btc
    if etf_alts:
        etf.update(etf_alts)
    etf = etf or None

    live_price = (market or {}).get("btc", {}).get("price")
    price_series = (cbbi or {}).get("price_series", {})

    # As funções de processamento (abaixo) não são fontes de rede, mas ainda
    # podem quebrar com dados inesperados. Blindamos cada uma: se falhar, vira
    # None e o build continua — nunca deixamos o processamento derrubar tudo.
    def safe(nome, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            SOURCES[nome] = {"ok": False, "detail": f"proc: {type(exc).__name__}: {exc}"}
            print(f"[falha proc] {nome}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return None

    models = safe("Modelos de preço", lambda: price_models(price_series, live_price))
    clock = safe("Relógio de ciclo", lambda: cycle_clock((net or {}).get("block_height")))
    chart = safe("Gráfico", lambda: build_chart_series(
        price_series, (cbbi or {}).get("metrics", {}), MANUAL_CHART_LINES))
    insights = safe("Insights", lambda: build_insights(
        (cbbi or {}).get("metrics", {}), models, derivs, fng, market, altseason))

    data = {
        "generated_at": now.isoformat(),
        "generated_at_br": (now - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M"),
        "cbbi": (cbbi or {}).get("metrics", {}),
        "models": models,
        "cycle": clock,
        "market": market,
        "derivatives": derivs,
        "fear_greed": fng,
        "altseason": altseason,
        "etf": etf,
        "insights": insights,
        "network": net,
        "macro": macro,
        "sources": SOURCES,
    }

    (ROOT / "data.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Gráfico vai em arquivo separado (maior, muda devagar).
    if chart:
        (ROOT / "chart.json").write_text(
            json.dumps(chart, ensure_ascii=False), encoding="utf-8"
        )
        print(f"chart.json gravado — {len(chart['points'])} pontos semanais")

    ok = sum(1 for s in SOURCES.values() if s["ok"])
    print(f"data.json gravado — {ok}/{len(SOURCES)} itens responderam")
    for name, st in SOURCES.items():
        print(f"  {'OK  ' if st['ok'] else 'FALHA'} {name}: {st['detail']}")

    # Só abortamos se as FONTES DE REDE principais caíram todas. As entradas de
    # processamento (Modelos, Gráfico, Insights, Relógio) não contam aqui —
    # elas dependem das fontes, não são fontes.
    proc_names = {"Modelos de preço", "Relógio de ciclo", "Gráfico", "Insights"}
    fontes_ok = sum(1 for n, s in SOURCES.items() if n not in proc_names and s["ok"])
    if fontes_ok == 0:
        sys.exit("Nenhuma fonte de rede respondeu — abortando para não gravar painel vazio.")


if __name__ == "__main__":
    main()
