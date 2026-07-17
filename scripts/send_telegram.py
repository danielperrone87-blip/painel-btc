#!/usr/bin/env python3
"""Resumo do fechamento diário (00:00 UTC = 21h BRT) no Telegram.

Lê o data.json que o build_data.py acabou de gerar. Token e chat_id vêm de
GitHub Secrets — nunca ficam no código.
"""

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PANEL_URL = os.environ.get("PANEL_URL", "")


def num(v, prefix="", suffix="", dec=2):
    if v is None:
        return "—"
    return f"{prefix}{v:,.{dec}f}{suffix}".replace(",", "@").replace(".", ",").replace("@", ".")


def pct(v, dec=1):
    if v is None:
        return "—"
    return f"{'+' if v >= 0 else ''}{v:.{dec}f}%".replace(".", ",")


def lvl(v, dec=1):
    """Nível percentual (dominância). Diferente de pct(): não leva sinal de +."""
    if v is None:
        return "—"
    return f"{v:.{dec}f}%".replace(".", ",")


def big(v):
    """US$ 31,0 B em vez de US$ 31.000.000.000."""
    if v is None:
        return "—"
    a = abs(v)
    for div, suf in ((1e12, " T"), (1e9, " B"), (1e6, " M")):
        if a >= div:
            return num(v / div, "US$ ", suf, 1)
    return num(v, "US$ ", dec=0)


def arrow(v):
    if v is None:
        return "·"
    return "🟢" if v >= 0 else "🔴"


def pct_flow(v):
    """Fluxo de ETF em US$mi, com sinal e emoji de direção."""
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    emoji = "🟢" if v >= 0 else "🔴"
    return f"{emoji} {sign}{v:,.1f}".replace(",", "@").replace(".", ",").replace("@", ".")


def build_message(d):
    m = d.get("models") or {}
    mk = d.get("market") or {}
    btc = mk.get("btc") or {}
    cb = d.get("cbbi") or {}
    dv = d.get("derivatives") or {}
    fg = d.get("fear_greed") or {}
    cy = d.get("cycle") or {}

    L = []
    L.append("<b>₿ FECHAMENTO DIÁRIO — 21h</b>")
    L.append(f"<i>{d.get('generated_at_br','')}</i>")
    L.append("")

    L.append(
        f"<b>BTC {num(btc.get('price'), 'US$ ', dec=0)}</b>  "
        f"{arrow(btc.get('chg24h'))} {pct(btc.get('chg24h'))} (24h)"
    )
    L.append(
        f"7d {pct(btc.get('chg7d'))} · 30d {pct(btc.get('chg30d'))} · "
        f"do topo {pct(m.get('drawdown_from_ath'))}"
    )
    L.append("")

    # --- ciclo
    conf = (cb.get("confidence") or {}).get("score")
    L.append("<b>CICLO</b>")
    if conf is not None:
        L.append(f"CBBI (confiança de topo): <b>{conf:.0f}/100</b>")
    L.append(
        f"Mayer {num(m.get('mayer_multiple'), dec=2)} · "
        f"2Y MA {num(m.get('ma730_multiple'), dec=2)}x "
        f"({num(m.get('ma730'), 'US$ ', dec=0)})"
    )
    gap = m.get("pi_cycle_gap_pct")
    if gap is not None:
        estado = "CRUZOU ⚠️" if gap >= 0 else f"{abs(gap):.0f}% abaixo".replace(".", ",")
        L.append(f"Pi Cycle: {estado}")

    ordem = ["mvrv", "puell", "rupl", "rhodl", "reserverisk", "woobull"]
    linhas = [
        f"{cb[k]['label']}: {cb[k]['score']:.0f}"
        for k in ordem if k in cb
    ]
    if linhas:
        L.append("<i>" + " · ".join(linhas) + "</i>")
    L.append(f"Dias desde o halving: {cy.get('days_since_halving','—')}")
    L.append("")

    # --- risco
    L.append("<b>RISCO</b>")
    L.append(
        f"Funding {pct(dv.get('funding_rate_pct'), 4)} · "
        f"OI {big(dv.get('open_interest_usd'))}"
    )
    if fg.get("value") is not None:
        L.append(f"Medo & Ganância: {fg['value']} ({fg.get('label','')})")
    dom = (mk.get("dominance") or {})
    L.append(f"Dominância BTC {lvl(dom.get('btc'))} · ETH {lvl(dom.get('eth'))}")
    L.append("")

    # --- altcoins
    L.append("<b>ALTCOINS (24h · 7d vs BTC)</b>")
    for a in (mk.get("alts") or []):
        if a.get("missing"):
            L.append(f"{a['symbol']}: — (id não resolveu)")
            continue
        vb = a.get("chg7d_btc")
        vb_txt = f" · vs BTC 7d {pct(vb)}" if vb is not None else ""
        marca = "🎯" if a.get("vs_btc_focus") else ""
        L.append(
            f"{marca}<b>{a['symbol']}</b> {num(a.get('price'), 'US$ ', dec=4 if (a.get('price') or 0) < 10 else 2)} "
            f"{arrow(a.get('chg24h'))} {pct(a.get('chg24h'))}{vb_txt}"
        )
    L.append("")

    # --- ETF
    etf = d.get("etf") or {}
    etf_order = [a for a in ("BTC", "ETH", "SOL", "HYPE") if a in etf]
    if etf_order:
        L.append("<b>ETF (fluxo do dia · US$mi)</b>")
        for a in etf_order:
            e = etf[a]
            ld = e.get("last_day")
            wk = e.get("week")
            L.append(f"{a}: {pct_flow(ld)} (dia) · {pct_flow(wk)} (sem)")
        L.append("")

    # --- macro
    macro = d.get("macro") or []
    if macro:
        L.append("<b>MACRO</b>")
        L.append(" · ".join(f"{x['label']} {pct(x.get('chg_pct'))}" for x in macro))
        L.append("")

    ruins = [n for n, s in (d.get("sources") or {}).items() if not s.get("ok")]
    if ruins:
        L.append(f"⚠️ <i>Fontes fora do ar: {', '.join(ruins)}</i>")

    if PANEL_URL:
        L.append(f'\n<a href="{PANEL_URL}">Abrir painel completo →</a>')

    return "\n".join(L)


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("TELEGRAM_TOKEN e TELEGRAM_CHAT_ID não configurados nos Secrets.")

    data = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
    msg = build_message(data)

    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not r.ok:
        sys.exit(f"Telegram recusou: {r.status_code} {r.text}")
    print("Resumo enviado.")


if __name__ == "__main__":
    main()
