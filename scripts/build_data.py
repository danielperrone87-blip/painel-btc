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
    CBBI_URL, CG_BASE, BINANCE_FUT, FNG_URL, MEMPOOL_BASE, STOOQ_BASE,
    HTTP_TIMEOUT, USER_AGENT, CBBI_LABELS,
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

    return out


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


@source("Binance (derivativos)")
def fetch_derivatives():
    prem = get_json(f"{BINANCE_FUT}/premiumIndex", params={"symbol": "BTCUSDT"})
    oi = get_json(f"{BINANCE_FUT}/openInterest", params={"symbol": "BTCUSDT"})
    mark = float(prem.get("markPrice") or 0)
    contracts = float(oi.get("openInterest") or 0)
    return {
        "funding_rate_pct": float(prem["lastFundingRate"]) * 100,
        "next_funding": prem.get("nextFundingTime"),
        "open_interest_btc": contracts,
        "open_interest_usd": contracts * mark if mark else None,
        "mark_price": mark or None,
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
    syms = "+".join(STOOQ_SYMBOLS)
    r = SESSION.get(STOOQ_BASE, timeout=HTTP_TIMEOUT, params={
        "s": syms, "f": "sd2t2ohlcv", "h": "", "e": "csv",
    })
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    out = []
    for row in rows:
        sym = (row.get("Symbol") or "").lower()
        try:
            close = float(row["Close"])
            openp = float(row["Open"])
        except (TypeError, ValueError, KeyError):
            continue  # símbolo não resolveu na Stooq
        out.append({
            "symbol": sym,
            "label": STOOQ_SYMBOLS.get(sym, sym.upper()),
            "close": close,
            "chg_pct": (close / openp - 1) * 100 if openp else None,
            "date": row.get("Date"),
        })
    if not out:
        raise RuntimeError("Stooq não retornou nenhum símbolo válido")
    return out


# ------------------------------------------------------------------- main

def main():
    now = datetime.now(timezone.utc)

    cbbi = fetch_cbbi()
    market = fetch_coingecko()
    derivs = fetch_derivatives()
    fng = fetch_fng()
    net = fetch_network()
    macro = fetch_macro()

    live_price = (market or {}).get("btc", {}).get("price")
    models = price_models((cbbi or {}).get("price_series", {}), live_price)
    clock = cycle_clock((net or {}).get("block_height"))

    data = {
        "generated_at": now.isoformat(),
        "generated_at_br": (now - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M"),
        "cbbi": (cbbi or {}).get("metrics", {}),
        "models": models,
        "cycle": clock,
        "market": market,
        "derivatives": derivs,
        "fear_greed": fng,
        "network": net,
        "macro": macro,
        "sources": SOURCES,
    }

    (ROOT / "data.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    ok = sum(1 for s in SOURCES.values() if s["ok"])
    print(f"data.json gravado — {ok}/{len(SOURCES)} fontes responderam")
    for name, st in SOURCES.items():
        print(f"  {'OK  ' if st['ok'] else 'FALHA'} {name}: {st['detail']}")

    # O build nunca falha por causa de uma fonte, mas se TUDO caiu algo está
    # errado de verdade (rede, bloqueio) e o Action deve gritar.
    if ok == 0:
        sys.exit("Nenhuma fonte respondeu — abortando para não gravar painel vazio.")


if __name__ == "__main__":
    main()
