#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Ipotesi di strategia US30 (v1, 2026-09-03)
═══════════════════════════════════════════════════════════

Girano dentro scripts/us30_harness.py. Firma:

    fn(candles, ind, i, dt) -> 'buy' | 'sell' | None

`ind` = output di strategy-engine-v2.compute_all (atr, adx/dip/dim, rsi, bb_*,
e20/e50/e200, st, vwap, macd*, ...). `dt` = datetime UTC aware della candela `i`.

Profilo US30Cash (da directives/01_data_sources.md): range giornaliero mediano
~584 pt, ATR H1 ~88 pt, volatilità concentrata 15:00–21:00 UTC (apertura cash USA),
solo ~32% di barre H1 "direzionali" → bias mean-reverting fuori dalla sessione USA,
trend vero dentro. Le 3 ipotesi sotto attaccano angoli diversi di questo profilo.
"""

# ── helper: hour/date da epoch senza datetime ────────────────────────────────
def _hour(ts):  return (ts // 3600) % 24
def _date(ts):  return ts // 86400


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ORB — Opening Range Breakout della sessione cash USA
#    Ipotesi: il range dei primi ~90 min dopo l'apertura di Wall Street contiene
#    l'informazione; una rottura pulita di quel range prosegue nella giornata.
# ═══════════════════════════════════════════════════════════════════════════════
def orb_breakout(candles, ind, i, dt, *, or_start=13, or_end=15,
                 trade_until=20, w_min=0.3, w_max=2.5):
    ts = candles[i]['t']
    h = _hour(ts)
    if not (or_end <= h < trade_until):
        return None
    today = _date(ts)
    av = ind['atr'][i]
    if not av:
        return None

    # costruisci l'opening range di oggi (finestra [or_start, or_end) UTC)
    or_hi = None; or_lo = None; seen = 0
    for k in range(i, max(i - 96, 0), -1):
        tk = candles[k]['t']
        if _date(tk) != today:
            break
        hk = _hour(tk)
        if or_start <= hk < or_end:
            or_hi = candles[k]['h'] if or_hi is None else max(or_hi, candles[k]['h'])
            or_lo = candles[k]['l'] if or_lo is None else min(or_lo, candles[k]['l'])
            seen += 1
    if or_hi is None or seen < 2:
        return None

    width = or_hi - or_lo
    if width < w_min * av or width > w_max * av:
        return None   # range troppo stretto (rumore) o troppo largo (già mosso)

    c = candles[i]['c']
    # rottura confermata dalla close della candela
    if c > or_hi and candles[i]['o'] <= or_hi + 0.5 * av:
        return 'buy'
    if c < or_lo and candles[i]['o'] >= or_lo - 0.5 * av:
        return 'sell'
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BB_FADE — mean-reversion sulle estensioni di Bollinger fuori sessione trend
#    Ipotesi: nelle ore di chop (68% delle barre) un tocco di banda con RSI
#    estremo e ADX basso rientra verso la media.
# ═══════════════════════════════════════════════════════════════════════════════
def bb_fade(candles, ind, i, dt, *, rsi_lo=28, rsi_hi=72, adx_max=22,
            skip_hours=(15, 16, 17)):
    if _hour(candles[i]['t']) in skip_hours:
        return None
    c = ind['C'][i]
    bu, bl = ind['bb_up'][i], ind['bb_lo'][i]
    r = ind['rsi'][i]
    a = ind['adx'][i]
    if None in (bu, bl, r, a):
        return None
    if a >= adx_max:
        return None   # c'è trend → non fare fade
    if c <= bl and r <= rsi_lo:
        return 'buy'
    if c >= bu and r >= rsi_hi:
        return 'sell'
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SESSION_MOMENTUM — trend-following nella sessione USA
#    Ipotesi: quando un trend vero esiste, si sviluppa 15:00–21:00 UTC; entrare
#    in direzione di Supertrend + ADX in salita sopra soglia.
# ═══════════════════════════════════════════════════════════════════════════════
def session_momentum(candles, ind, i, dt, *, adx_min=22, sess=(14, 21)):
    if not (sess[0] <= _hour(candles[i]['t']) < sess[1]):
        return None
    st = ind['st'][i]
    a = ind['adx'][i]; ap = ind['adx'][i - 2]
    dip, dim = ind['dip'][i], ind['dim'][i]
    c = ind['C'][i]; e50 = ind['e50'][i]
    if None in (st, a, ap, dip, dim, e50):
        return None
    if a < adx_min or a <= ap:
        return None   # serve ADX sopra soglia E in salita
    if st > 0 and dip > dim and c > e50:
        return 'buy'
    if st < 0 and dim > dip and c < e50:
        return 'sell'
    return None


# ── registro per l'harness ───────────────────────────────────────────────────
REGISTRY = [
    {'name': 'orb_breakout',     'fn': orb_breakout,
     'tfs': ['M15', 'M30'],
     'params': dict(tp_mult=2.2, sl_mult=1.2, session=(14, 21), max_trades_day=2, cooldown_bars=4)},
    {'name': 'bb_fade',          'fn': bb_fade,
     'tfs': ['M30', 'H1'],
     'params': dict(tp_mult=1.6, sl_mult=1.4, session=(0, 24), max_trades_day=3, cooldown_bars=3)},
    {'name': 'session_momentum', 'fn': session_momentum,
     'tfs': ['H1', 'M30'],
     'params': dict(tp_mult=2.8, sl_mult=1.6, session=(14, 21), max_trades_day=2, cooldown_bars=2)},
]
