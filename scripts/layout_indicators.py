#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Indicatori dei layout TradingView XAU_* (2026-09-10)
════════════════════════════════════════════════════════════════════════════════
Source of truth CONDIVISA (regola CLAUDE.md: mai duplicare logica).
Importato da:
  • strategy-engine-v2.py::compute_all()     (backtest)
  • mt5-bot.py::compute_indicators()         (live)

Inventario reale dei 5 layout TradingView XAU (verificato 2026-09-10 leggendo il
widget di ogni layout — non le strategie Pine salvate):

  1. MFKK_GOLD      H1  → Gold Watch Evans 4.0 · Smart Money Tool · CCI Stoch · MACD · ADX/DI
                         = S00_MFKK (già live, non gestito qui)
  2. Default        M15 → Sessions [LuxAlgo] · Trendlines with Breaks [LuxAlgo] ·
                         Pivot Points Standard · Key Levels SpacemanBTC IDWM · EMA200
                         = S31_LAYOUT_SMART  (funzioni ls_* in signals.py)
  3. XAU_M15        M5  → Bollinger Bands · ICT Institutional Order Flow (fadi) ·
                         EMA 20/50/100/200 · Order Block Finder · OBV
                         = S32_ORDERFLOW_SCALP  (funzioni s32_* in signals.py)
  4. XAU_M30        M30 → Supertrend · Williams Alligator · OBV MACD Indicator ·
                         Ultimate RSI [LuxAlgo] · Momentum
                         = S33_TREND_MOMENTUM  (funzioni s33_* in signals.py)
  5. XAU_H1_Volumes H1  → Volume Footprint (Leviathan) · Visible Range Volume Profile ·
                         Session Volume Profile · Cumulative Delta Volume · Normalized Volume
                         = S34_VOLUME_AUCTION  (funzioni s34_* in signals.py)

Questo modulo porta gli indicatori dei layout 2-5 (il layout 1 = S00 usa i suoi):
  - Trendlines with Breaks [LuxAlgo]   length=14, slope calc = ATR×1
  - Pivot Points Standard              type Fibonacci, anchor giornaliero
  - Key Levels SpacemanBTC IDWM        PDH/PDL, PWH/PWL, H/L sessioni, prev-4H, day open
  - Moving Average Exponential          EMA 200 (close) — vero EMA200, non l'alias e233
  - Ultimate RSI [LuxAlgo]             length=14 (RMA) + signal EMA=14
  - Cumulative Delta Volume            proxy da OHLCV (close-in-range), reset giornaliero
  - Volume Profile (rolling + sessione) POC / VAH / VAL (value area 70%)
  - Normalized Volume                  volume relativo su media 20

Tutti gli array sono CAUSALI (solo periodi/pivot già chiusi/confermati).
"""
import datetime

try:
    import numpy as _np
    _HAVE_NP = True
except Exception:  # pragma: no cover
    _HAVE_NP = False


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


def _ema_list(src, p):
    """EMA fallback puro-Python (usato solo se il chiamante non passa ema_fn)."""
    n = len(src); out = [None] * n; k = 2.0 / (p + 1.0); acc = None
    for i in range(n):
        x = src[i]
        if x is None:
            out[i] = acc
            continue
        acc = x if acc is None else (x - acc) * k + acc
        out[i] = acc
    return out


def ultimate_rsi(src, length=14, smooth=14):
    """Ultimate RSI [LuxAlgo] — porta fedele (smoType1=RMA, smoType2=EMA).
        upper = highest(src,length); lower = lowest(src,length); r = upper-lower
        d = src-src[1];  diff = r > r[1] ? r : |d|
        num = rma(d, length)            (segnato)
        den = rma(diff, length)         (non segnato)
        arsi = 50*num/den + 50          (oscillatore 0..100, ~50 neutro, come RSI)
        signal = ema(arsi, smooth)
    Ritorna (arsi, signal). Causale."""
    n = len(src)
    arsi = [None] * n
    if n < length + 2:
        return arsi, [None] * n
    num_acc = den_acc = None
    r_prev = None
    for i in range(n):
        if i < length:
            continue
        win = src[i - length + 1:i + 1]
        upper = max(win); lower = min(win)
        r = upper - lower
        d = src[i] - src[i - 1]
        if r_prev is not None and r > r_prev:
            diff = r
        else:
            diff = abs(d)
        if num_acc is None:
            num_acc = d; den_acc = diff
        else:
            num_acc = (num_acc * (length - 1) + d) / length
            den_acc = (den_acc * (length - 1) + diff) / length
        arsi[i] = (50.0 * num_acc / den_acc + 50.0) if den_acc else 50.0
        r_prev = r
    sig = _ema_list([x if x is not None else 50.0 for x in arsi], smooth)
    sig = [None if arsi[i] is None else sig[i] for i in range(n)]
    return arsi, sig


def momentum_roc(C, p=10):
    """Momentum classico (differenza, non %): src - src[p]. Come lo study 'Momentum' TV."""
    n = len(C); out = [None] * n
    for i in range(p, n):
        out[i] = C[i] - C[i - p]
    return out


def cvd_proxy(candles):
    """Cumulative Delta Volume da OHLCV (proxy 'close position in range'), reset per
    giorno UTC (come l'anchor di default del CVD di TradingView).
      delta_bar = V * (2C - H - L) / (H - L)     (∈ [-V, +V])
    Ritorna dict:
      cvd        -> cumulativa giornaliera del delta
      cvd_delta  -> delta della singola barra
      cvd_ema    -> EMA(9) del delta (pressione recente)
    Causale (usa solo la barra i)."""
    n = len(candles)
    cvd = [0.0] * n; delta = [0.0] * n
    cur_day = None; run = 0.0
    for i, c in enumerate(candles):
        d = datetime.datetime.utcfromtimestamp(c['t']).date()
        rng = c['h'] - c['l']
        db = (c['v'] * (2 * c['c'] - c['h'] - c['l']) / rng) if rng > 0 else 0.0
        delta[i] = db
        if d != cur_day:
            cur_day = d; run = 0.0
        run += db
        cvd[i] = run
    return {'cvd': cvd, 'cvd_delta': delta, 'cvd_ema': _ema_list(delta, 9)}


def rel_volume(V, length=20):
    """Normalized / Relative Volume: V / SMA(V, length). 1.0 = media. Causale."""
    n = len(V); out = [None] * n; s = 0.0
    for i in range(n):
        s += V[i]
        if i >= length:
            s -= V[i - length]
        if i >= length - 1:
            avg = s / length
            out[i] = (V[i] / avg) if avg > 0 else None
    return out


def _profile_levels(prices_hi, prices_lo, vols, n_bins=48, va_pct=0.70):
    """Volume profile su un blocco di barre -> (poc, vah, val) o (None,None,None).
    Distribuisce il volume di ogni barra uniformemente sui bin che copre."""
    lo = min(prices_lo); hi = max(prices_hi)
    if not (hi > lo):
        return None, None, None
    step = (hi - lo) / n_bins
    bins = [0.0] * n_bins
    for h, l, v in zip(prices_hi, prices_lo, vols):
        b0 = int((l - lo) / step); b1 = int((h - lo) / step)
        b0 = 0 if b0 < 0 else (n_bins - 1 if b0 >= n_bins else b0)
        b1 = 0 if b1 < 0 else (n_bins - 1 if b1 >= n_bins else b1)
        share = v / (b1 - b0 + 1)
        for b in range(b0, b1 + 1):
            bins[b] += share
    total = sum(bins)
    if total <= 0:
        return None, None, None
    poc_b = max(range(n_bins), key=lambda b: bins[b])
    acc = bins[poc_b]; lo_b = hi_b = poc_b
    target = total * va_pct
    while acc < target and (lo_b > 0 or hi_b < n_bins - 1):
        down = bins[lo_b - 1] if lo_b > 0 else -1.0
        up = bins[hi_b + 1] if hi_b < n_bins - 1 else -1.0
        if up >= down:
            hi_b += 1; acc += bins[hi_b]
        else:
            lo_b -= 1; acc += bins[lo_b]
    poc = lo + (poc_b + 0.5) * step
    vah = lo + (hi_b + 1) * step
    val = lo + lo_b * step
    return poc, vah, val


def rolling_volume_profile(candles, lookback=120, step_bars=3, n_bins=48, va_pct=0.70):
    """Visible-Range Volume Profile (proxy): profilo sulle ultime `lookback` barre chiuse.
    Ricalcolato ogni `step_bars` barre e forward-fill (perf). Causale.
    Ritorna dict con vp_poc / vp_vah / vp_val."""
    n = len(candles)
    H = [c['h'] for c in candles]; L = [c['l'] for c in candles]; Vv = [c['v'] for c in candles]
    poc = [None] * n; vah = [None] * n; val = [None] * n
    last = (None, None, None)
    for i in range(n):
        if i >= lookback and (i % step_bars == 0 or last[0] is None):
            a = i - lookback + 1
            last = _profile_levels(H[a:i + 1], L[a:i + 1], Vv[a:i + 1], n_bins, va_pct)
        poc[i], vah[i], val[i] = last
    return {'vp_poc': poc, 'vp_vah': vah, 'vp_val': val}


def session_volume_profile(candles, n_bins=48, va_pct=0.70):
    """Session Volume Profile. Per ogni barra i:
      svp_*      -> profilo della sessione IN CORSO (dallo start sessione a i) — developing
      psvp_*     -> profilo dell'ULTIMA sessione COMPLETATA — livelli fissi causali
    Sessioni UTC: Asia 0-7, London 7-13, NY 13-21 (fuori sessione -> 'off', propaga l'ultimo).
    """
    n = len(candles)
    out = {k: [None] * n for k in ('svp_poc', 'svp_vah', 'svp_val',
                                   'psvp_poc', 'psvp_vah', 'psvp_val')}

    def sess_of(h):
        if 0 <= h < 7:   return 'asia'
        if 7 <= h < 13:  return 'london'
        if 13 <= h < 21: return 'ny'
        return 'off'

    cur = None; cur_key = None
    accH = []; accL = []; accV = []
    prev = (None, None, None)
    for i, c in enumerate(candles):
        dt = datetime.datetime.utcfromtimestamp(c['t'])
        s = sess_of(dt.hour)
        key = (dt.date(), s)
        if s != 'off' and key != cur_key:
            # sessione precedente chiusa -> calcola livelli fissi
            if accH:
                prev = _profile_levels(accH, accL, accV, n_bins, va_pct)
            cur_key = key; accH = []; accL = []; accV = []
        if s != 'off':
            accH.append(c['h']); accL.append(c['l']); accV.append(c['v'])
            dev = _profile_levels(accH, accL, accV, n_bins, va_pct) if len(accH) >= 3 else (None, None, None)
        else:
            dev = (None, None, None)
        out['svp_poc'][i], out['svp_vah'][i], out['svp_val'][i] = dev
        out['psvp_poc'][i], out['psvp_vah'][i], out['psvp_val'][i] = prev
    return out


def compute_layout_indicators(candles, ema_fn=None):
    """Bundle completo per compute_all / compute_indicators. `ema_fn(list, period)` è la
    funzione EMA del chiamante (già presente in entrambi i moduli); se None usa quella
    interna."""
    ema_fn = ema_fn or _ema_list
    H = [c['h'] for c in candles]; L = [c['l'] for c in candles]
    C = [c['c'] for c in candles]; V = [c['v'] for c in candles]
    tlb_up, tlb_dn, tlb_upper, tlb_lower, tlb_up_s, tlb_dn_s = luxalgo_trendline_breaks(H, L, C, 14, 1.0)
    arsi, arsi_sig = ultimate_rsi(C, 14, 14)
    out = {
        # ── layout Default / S31 ──
        'ema200': ema_fn(C, 200),
        'tlb_up': tlb_up, 'tlb_dn': tlb_dn, 'tlb_upper': tlb_upper, 'tlb_lower': tlb_lower,
        'tlb_up_s': tlb_up_s, 'tlb_dn_s': tlb_dn_s,
        # ── layout XAU_M30 / S33 ──
        'ursi': arsi, 'ursi_sig': arsi_sig,
        'lmom': momentum_roc(C, 10),
        # ── layout XAU_H1_Volumes / S34 ──
        'rvol': rel_volume(V, 20),
    }
    out.update(daily_fib_pivots(candles))
    out.update(session_levels(candles))
    out.update(cvd_proxy(candles))
    out.update(rolling_volume_profile(candles))
    out.update(session_volume_profile(candles))
    return out
