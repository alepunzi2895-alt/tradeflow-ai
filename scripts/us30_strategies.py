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


# ═══════════════════════════════════════════════════════════════════════════════
# v2 — "come Wall Street": mean-reversion di un estremo di breve NELLA DIREZIONE
# del trend di fondo. È l'edge azionario più documentato e duraturo (Connors
# RSI(2), "buy weakness in strength"): gli indici sovra-reagiscono nel breve e
# rimbalzano verso la media finché il trend primario regge. Non è fade cieco.
# ═══════════════════════════════════════════════════════════════════════════════
def _rsi_n(C, i, n):
    """RSI di Wilder su n periodi calcolato al bar i (serve RSI(2)/RSI(3))."""
    if i <= n:
        return None
    gains = 0.0; losses = 0.0
    for k in range(i - n + 1, i + 1):
        ch = C[k] - C[k - 1]
        if ch >= 0: gains += ch
        else:       losses -= ch
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def dow_dip(candles, ind, i, dt, *, rsi_len=3, rsi_buy=12,
            max_stretch=4.0, look=20, sess=(13, 20)):
    """H1/H4 — pullback di breve in un trend di fondo intatto. **LONG-ONLY**:
    l'equity risk premium fa driftare gli indici al rialzo → il dip-buy in trend
    ha edge, il rip-sell (short mean-reversion) no. close>EMA200 & EMA50>EMA200
    & RSI(3)<12 & il calo dal massimo recente < 4×ATR (dip, non crollo).
    Sessione USA per fill affidabili."""
    if not (sess[0] <= _hour(candles[i]['t']) < sess[1]):
        return None
    C = ind['C']; e50 = ind['e50'][i]; e200 = ind['e200'][i]; av = ind['atr'][i]
    if None in (e50, e200, av) or not av:
        return None
    r = _rsi_n(C, i, rsi_len)
    if r is None:
        return None
    c = C[i]
    hi = max(C[max(i - look, 0):i + 1])
    if c > e200 and e50 > e200 and r < rsi_buy and (hi - c) < max_stretch * av:
        return 'buy'
    return None


from signals import signal_dow_dip as _signal_dow_dip  # source of truth


def dow_dip_d1(candles, ind, i, dt, **kw):
    """**S30_DOW_DIP** — wrapper sull'implementazione canonica in signals.py
    (`signal_dow_dip`). Mean-reversion azionaria Connors RSI(2), long-only, H4.
    Setup e razionale: vedi signals.py. Exit: TP 1.2×ATR / SL 2.6×ATR / no
    trailing / time-stop 18 barre H4."""
    return _signal_dow_dip(ind, i)


def vwap_reclaim(candles, ind, i, dt, *, sess=(13, 18), adx_min=14):
    """M30 — difesa del VWAP nella sessione USA: il prezzo era sotto VWAP nelle
       ultime barre e ci richiude sopra, con EMA200 in salita → i compratori
       istituzionali difendono il prezzo medio ponderato. Speculare short."""
    if not (sess[0] <= _hour(candles[i]['t']) < sess[1]):
        return None
    vw = ind['vwap']; C = ind['C']; e200 = ind['e200']; a = ind['adx'][i]
    if i < 12 or a is None or a < adx_min:
        return None
    v_i, v_p = vw[i], vw[i - 1]
    if None in (v_i, v_p, e200[i], e200[i - 10]):
        return None
    below_recent = any(C[k] < vw[k] for k in range(i - 3, i) if vw[k] is not None)
    slope_up   = e200[i] > e200[i - 10]
    slope_down = e200[i] < e200[i - 10]
    if C[i] > v_i and C[i - 1] <= v_p and below_recent and slope_up:
        return 'buy'
    above_recent = any(C[k] > vw[k] for k in range(i - 3, i) if vw[k] is not None)
    if C[i] < v_i and C[i - 1] >= v_p and above_recent and slope_down:
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
    # v2 — Wall Street mean-reversion (long-only, no trailing: si aspetta lo snap-back)
    {'name': 'dow_dip',          'fn': dow_dip,
     'tfs': ['H1', 'H4'],
     'params': dict(tp_mult=1.3, sl_mult=2.6, session=(13, 20), max_trades_day=1,
                    cooldown_bars=6, be_trail=False)},
    {'name': 'dow_dip_d1',       'fn': dow_dip_d1,     # ← candidata roster (S30_DOW_DIP)
     'tfs': ['H4'],
     'params': dict(tp_mult=1.2, sl_mult=2.6, session=(0, 24), max_trades_day=1,
                    cooldown_bars=1, be_trail=False)},
    {'name': 'vwap_reclaim',     'fn': vwap_reclaim,
     'tfs': ['M30', 'H1'],
     'params': dict(tp_mult=2.2, sl_mult=1.6, session=(13, 18), max_trades_day=2, cooldown_bars=3)},
]
