#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Indicatori dei layout TradingView XAU_* (2026-09-10)
════════════════════════════════════════════════════════════════════════════════
Source of truth CONDIVISA (regola CLAUDE.md: mai duplicare logica).
Importato da:
  • strategy-engine-v2.py::compute_all()     (backtest)
  • mt5-bot.py::compute_indicators()         (live)

Porta i 4 indicatori dei layout XAU_M15 / XAU_M30 / XAU_H1_Volumes / Default
(tutti tranne MFKK_GOLD = S00):
  - Trendlines with Breaks [LuxAlgo]   length=14, slope calc = ATR×1
  - Pivot Points Standard              type Fibonacci, anchor giornaliero
  - Key Levels SpacemanBTC IDWM        PDH/PDL, PWH/PWL, H/L sessioni, prev-4H, day open
  - Moving Average Exponential          EMA 200 (close) — vero EMA200, non l'alias e233

Tutti gli array sono CAUSALI (solo periodi/pivot già chiusi/confermati).
Usati da S31_LAYOUT_SMART (signals.ls_scan / ls_manage_step) e dalle signal fn SA-SF.
"""
import datetime


def _rma(src, p):
    """Wilder RMA (== ta.rma / base di ta.atr in Pine)."""
    n = len(src); out = [None] * n; acc = None
    for i in range(n):
        xv = src[i] if src[i] is not None else 0.0
        if acc is None:
            if i >= p - 1:
                acc = sum((src[j] if src[j] is not None else 0.0) for j in range(i - p + 1, i + 1)) / p
                out[i] = acc
        else:
            acc = (acc * (p - 1) + xv) / p
            out[i] = acc
    return out


def _atr_wilder(h, l, c, p=14):
    tr = [0.0]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return _rma(tr, p)


def luxalgo_trendline_breaks(h, l, c, length=14, mult=1.0):
    """Port di 'Trendlines with Breaks [LuxAlgo]' (slope calc = Atr).
    Ritorna (up_break, dn_break, upper, lower, up_break_s, dn_break_s):
      *_break   -> crossover della linea PROIETTATA (alertcondition ufficiale:
                   ta.crossover(src, upper - slope*length)) -- trigger largo
      *_break_s -> crossover della linea al valore CORRENTE (close > upper) -- stretto
      upper/lower -> valore corrente delle due trendline
    Causale: ta.pivothigh(length,length) e' noto solo `length` barre dopo il pivot."""
    n = len(c)
    atrw = _atr_wilder(h, l, c, length)
    up_break = [False] * n; dn_break = [False] * n
    up_break_s = [False] * n; dn_break_s = [False] * n
    upper = [None] * n; lower = [None] * n
    U = 0.0; L = 0.0; slope_ph = 0.0; slope_pl = 0.0
    upos = dnos = upos_s = dnos_s = 0
    for i in range(n):
        ph = pl = False
        k = i - length
        if k >= length:
            wh = h[k - length:k + length + 1]; wl = l[k - length:k + length + 1]
            if h[k] == max(wh) and wh.count(h[k]) == 1:
                ph = True
            if l[k] == min(wl) and wl.count(l[k]) == 1:
                pl = True
        slope = (atrw[i] or 0.0) / length * mult
        if ph:
            slope_ph = slope
        if pl:
            slope_pl = slope
        U = h[k] if ph else U - slope_ph
        L = l[k] if pl else L + slope_pl
        upper[i] = U; lower[i] = L
        up_p, dn_p, up_ps, dn_ps = upos, dnos, upos_s, dnos_s
        if ph:
            upos = upos_s = 0
        else:
            if c[i] > U - slope_ph * length:
                upos = 1
            if c[i] > U:
                upos_s = 1
        if pl:
            dnos = dnos_s = 0
        else:
            if c[i] < L + slope_pl * length:
                dnos = 1
            if c[i] < L:
                dnos_s = 1
        up_break[i] = upos > up_p
        dn_break[i] = dnos > dn_p
        up_break_s[i] = upos_s > up_ps
        dn_break_s[i] = dnos_s > dn_ps
    return up_break, dn_break, upper, lower, up_break_s, dn_break_s


def session_levels(candles):
    """Key Levels SpacemanBTC IDWM (sottoinsieme robusto): H/L dell'ULTIMA sessione
    COMPLETATA di ogni tipo (Asia/London/NY) + prev-4H H/L + open del giorno corrente.
    Tutto causale (solo periodi chiusi). Finestre UTC (chart tz UTC+2 -> -2):
    Asia 00-07, London 07-13, NY 13-21."""
    n = len(candles)
    SESS = {'asia': (0, 7), 'london': (7, 13), 'ny': (13, 21)}
    out = {k: [None] * n for k in (
        'sess_asia_hi', 'sess_asia_lo', 'sess_lon_hi', 'sess_lon_lo', 'sess_ny_hi', 'sess_ny_lo',
        'p4h_hi', 'p4h_lo', 'day_open')}
    last = {s: [None, None] for s in SESS}
    acc = {s: [None, None, None] for s in SESS}
    day_o = None; cur_day = None
    blk_hi = blk_lo = None; blk_id = None; p4h = [None, None]
    for i, c in enumerate(candles):
        dt = datetime.datetime.utcfromtimestamp(c['t'])
        d = dt.date(); h = dt.hour
        if d != cur_day:
            cur_day = d; day_o = c['o']
            for s in SESS:
                if acc[s][0] is not None:
                    last[s] = [acc[s][0], acc[s][1]]
                    acc[s] = [None, None, None]
        out['day_open'][i] = day_o
        bid = int(c['t']) // (4 * 3600)
        if bid != blk_id:
            if blk_id is not None:
                p4h = [blk_hi, blk_lo]
            blk_id = bid; blk_hi = c['h']; blk_lo = c['l']
        else:
            blk_hi = max(blk_hi, c['h']); blk_lo = min(blk_lo, c['l'])
        out['p4h_hi'][i], out['p4h_lo'][i] = p4h
        for s, (a, b) in SESS.items():
            if a <= h < b:
                if acc[s][2] != d:
                    if acc[s][0] is not None:
                        last[s] = [acc[s][0], acc[s][1]]
                    acc[s] = [c['h'], c['l'], d]
                else:
                    acc[s][0] = max(acc[s][0], c['h']); acc[s][1] = min(acc[s][1], c['l'])
            elif h >= b and acc[s][2] == d and acc[s][0] is not None:
                last[s] = [acc[s][0], acc[s][1]]; acc[s] = [None, None, None]
        out['sess_asia_hi'][i], out['sess_asia_lo'][i] = last['asia']
        out['sess_lon_hi'][i], out['sess_lon_lo'][i] = last['london']
        out['sess_ny_hi'][i], out['sess_ny_lo'][i] = last['ny']
    return out


def daily_fib_pivots(candles):
    """Pivot Points Standard, type Fibonacci, anchor giornaliero (come layout XAU_M15).
    Per ogni barra i: P/R1-3/S1-3 dal giorno UTC precedente COMPLETO + PDH/PDL (prev day)
    e PWH/PWL (prev ISO week). Interamente causale (solo periodi gia' chiusi)."""
    n = len(candles)
    day_hl = {}
    for c in candles:
        d = datetime.datetime.utcfromtimestamp(c['t']).date()
        if d not in day_hl:
            day_hl[d] = [c['h'], c['l'], c['c']]
        else:
            day_hl[d][0] = max(day_hl[d][0], c['h'])
            day_hl[d][1] = min(day_hl[d][1], c['l'])
            day_hl[d][2] = c['c']
    days = sorted(day_hl)
    prev_day = {d: (days[k - 1] if k > 0 else None) for k, d in enumerate(days)}
    wk_hl = {}
    for d, (H_, L_, C_) in day_hl.items():
        wk = d.isocalendar()[:2]
        if wk not in wk_hl:
            wk_hl[wk] = [H_, L_]
        else:
            wk_hl[wk][0] = max(wk_hl[wk][0], H_); wk_hl[wk][1] = min(wk_hl[wk][1], L_)
    wks = sorted(wk_hl)
    prev_wk = {w: (wks[k - 1] if k > 0 else None) for k, w in enumerate(wks)}

    out = {k: [None] * n for k in ('dpiv', 'dr1', 'dr2', 'dr3', 'ds1', 'ds2', 'ds3',
                                   'pdh', 'pdl', 'pwh', 'pwl')}
    for i, c in enumerate(candles):
        d = datetime.datetime.utcfromtimestamp(c['t']).date()
        pd_ = prev_day.get(d)
        if pd_ is not None:
            ph, pl, pc = day_hl[pd_]
            rng = ph - pl
            p = (ph + pl + pc) / 3.0
            out['dpiv'][i] = p; out['pdh'][i] = ph; out['pdl'][i] = pl
            out['dr1'][i] = p + 0.382 * rng; out['dr2'][i] = p + 0.618 * rng; out['dr3'][i] = p + rng
            out['ds1'][i] = p - 0.382 * rng; out['ds2'][i] = p - 0.618 * rng; out['ds3'][i] = p - rng
        pw = prev_wk.get(d.isocalendar()[:2])
        if pw is not None:
            out['pwh'][i], out['pwl'][i] = wk_hl[pw]
    return out


def compute_layout_indicators(candles, ema_fn):
    """Bundle completo per compute_all / compute_indicators. `ema_fn(list, period)` è la
    funzione EMA del chiamante (già presente in entrambi i moduli)."""
    H = [c['h'] for c in candles]; L = [c['l'] for c in candles]; C = [c['c'] for c in candles]
    tlb_up, tlb_dn, tlb_upper, tlb_lower, tlb_up_s, tlb_dn_s = luxalgo_trendline_breaks(H, L, C, 14, 1.0)
    out = {
        'ema200': ema_fn(C, 200),
        'tlb_up': tlb_up, 'tlb_dn': tlb_dn, 'tlb_upper': tlb_upper, 'tlb_lower': tlb_lower,
        'tlb_up_s': tlb_up_s, 'tlb_dn_s': tlb_dn_s,
    }
    out.update(daily_fib_pivots(candles))
    out.update(session_levels(candles))
    return out
