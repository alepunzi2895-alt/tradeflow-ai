#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — S20_FIB_CONFLUENCE v2 (2026-08-28)

Il port fedele del Pine + lo sprint di tuning v1 (research_s20_fib.py) non hanno trovato
un edge robusto: WR 10-18%, unico candidato = picco isolato su M5.

Contesto: l'utente ha visto un trader live in profitto con questo Pine su M5/M1, ma
**discrezionale attivo** (sposta stop, esce a naso, seleziona i trigger). La v2 prova a
dare alle regole meccaniche le stesse difese che un umano applicherebbe:

  1. Ingresso CONFERMATO: zona/estremo + ribbon al bar j, poi bar j+1 conferma la direzione
     (close j+1 oltre close j) -> si entra al close di j+1. Niente coltelli che cadono.
  2. Higher-low / lower-high di STRUTTURA: il pullback deve tenere sopra (buy) / sotto (sell)
     lo swing precedente -> non entra contro un trend dritto.
  3. SL strutturale con floor ATR: sotto il minimo della candela-segnale con buffer, MAI
     piu' stretto di k*ATR. Niente ancoraggio a Fib 0.236.
  4. Filtro trend HTF: EMA200 su M5 (~16h di contesto) come proxy del "solo in trend".
  5. TP1 vicino (1R o Fib 0.5) + runner (2.5R o Fib 0.618), parziali 50/50, stop a BE dopo TP1.

Split cronologico 80% IS / 20% OOS. Un cambiamento e' adottabile solo con OOS PF > ~1.2
robusto sulle celle vicine e N ragionevole.

Uso: python -X utf8 scripts/research_s20_fib_v2.py
"""
import sys, os, importlib.util, itertools, datetime
from collections import defaultdict

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location("se2", os.path.join(HERE, "strategy-engine-v2.py"))
se2 = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]
spec.loader.exec_module(se2)

DATA = {
    'M5':  os.path.join(HERE, '..', 'data', 'xauusd_m5_mt5.json'),
    'M15': os.path.join(HERE, '..', 'data', 'xauusd_m15_mt5.json'),
    'M30': os.path.join(HERE, '..', 'data', 'xauusd_m30_mt5.json'),
}
SWING_LB = 50
SIG_LB   = 20
SESSION  = (7, 19)
STRUCT_NEAR, STRUCT_FAR = 10, 35   # finestra per higher-low / lower-high

CANDLES, IND = {}, {}


def load_data(quiet=False):
    """Carica candele + indicatori per M5/M15/M30 nei global CANDLES/IND. Lazy: chiamato da
    main() e dai tool che fanno backtest, NON all'import (così il paper tracker può importare
    solo le funzioni di segnale)."""
    if CANDLES:
        return
    if not quiet:
        print("Carico dati e calcolo indicatori...")
    for tf, path in DATA.items():
        c, _ = se2.load_from_file(path)
        CANDLES[tf] = c
        IND[tf] = se2.compute_all(c)
        if not quiet:
            print(f"  {tf}: {len(c)} barre")


def fib_levels(ind, i, swing=SWING_LB):
    if i < swing:
        return None
    H, L = ind['H'], ind['L']
    hi = max(H[i - swing + 1:i + 1]); lo = min(L[i - swing + 1:i + 1])
    rng = hi - lo
    if rng <= 0:
        return None
    return {'l236': lo + rng*0.236, 'l382': lo + rng*0.382, 'l500': lo + rng*0.500,
            'l618': lo + rng*0.618, 'l786': lo + rng*0.786}


def raw_conf(ind, j, P):
    """Zona estremo + ribbon al bar j (senza conferma, senza struttura)."""
    if j < max(SWING_LB, SIG_LB) + 2:
        return None
    H, L, C, O = ind['H'], ind['L'], ind['C'], ind['O']
    c, o = C[j], O[j]
    e20, e50 = ind['e20'][j], ind['e50'][j]
    if None in (c, o, e20, e50):
        return None
    lv = fib_levels(ind, j)
    if lv is None:
        return None
    rib_bull = e20 >= e50
    hi20 = max(H[j-SIG_LB+1:j+1]); lo20 = min(L[j-SIG_LB+1:j+1])
    band = (hi20 - lo20) * P['band']
    is_bot = L[j] <= lo20 + band and c > o
    is_top = H[j] >= hi20 - band and c < o
    buy  = is_bot and c < lv['l382'] and rib_bull
    sell = is_top and c > lv['l618'] and not rib_bull
    return (buy, sell)


def struct_ok(ind, i, direction):
    H, L = ind['H'], ind['L']
    if i < STRUCT_FAR + 1:
        return False
    if direction == 'buy':
        recent_low = min(L[i - STRUCT_NEAR + 1:i + 1])
        prior_low  = min(L[i - STRUCT_FAR:i - STRUCT_NEAR])
        return recent_low > prior_low          # higher-low: il pullback ha tenuto
    recent_high = max(H[i - STRUCT_NEAR + 1:i + 1])
    prior_high  = max(H[i - STRUCT_FAR:i - STRUCT_NEAR])
    return recent_high < prior_high            # lower-high


def htf_ok(ind, i, direction, mode):
    if mode == 'none':
        return True
    c = ind['C'][i]
    e200 = ind['e200'][i]; e50 = ind['e50'][i]
    if e200 is None:
        return False
    if mode == 'ema200':
        return c > e200 if direction == 'buy' else c < e200
    if mode == 'ema50_200':
        if e50 is None:
            return False
        return (c > e200 and e50 > e200) if direction == 'buy' else (c < e200 and e50 < e200)
    return True


def sig_at(ind, i, P):
    """Ritorna (dir, entry, sl, tp1, tp2) o None. Ingresso al bar i (= conferma di i-1)."""
    ts = CANDLES_CUR[i]['t']
    hour = datetime.datetime.utcfromtimestamp(ts).hour
    if not (SESSION[0] <= hour < SESSION[1]):
        return None

    rc = raw_conf(ind, i - 1, P)          # setup al bar precedente
    if rc is None:
        return None
    buy_setup, sell_setup = rc
    C = ind['C']
    if buy_setup and C[i] > C[i - 1]:      # bar i conferma verso l'alto
        direction = 'buy'
    elif sell_setup and C[i] < C[i - 1]:
        direction = 'sell'
    else:
        return None

    if not struct_ok(ind, i, direction):
        return None
    if not htf_ok(ind, i, direction, P['htf']):
        return None

    entry = C[i]
    atr = ind['atr'][i] or 0.0
    if atr <= 0:
        return None
    sigcandle_lo = ind['L'][i]; sigcandle_hi = ind['H'][i]
    buf = 0.15 * atr

    if direction == 'buy':
        sl = min(sigcandle_lo - buf, entry - P['sl_atr_k'] * atr)
        risk = entry - sl
        if risk <= 0:
            return None
        tp1 = entry + risk * 1.0 if P['tp1'] == 'r1' else fib_levels(ind, i)['l500']
        tp2 = entry + risk * P['tp2_r']
        if not (tp1 > entry):
            return None
    else:
        sl = max(sigcandle_hi + buf, entry + P['sl_atr_k'] * atr)
        risk = sl - entry
        if risk <= 0:
            return None
        tp1 = entry - risk * 1.0 if P['tp1'] == 'r1' else fib_levels(ind, i)['l500']
        tp2 = entry - risk * P['tp2_r']
        if not (tp1 < entry):
            return None

    reward = abs(tp1 - entry)
    if reward / risk < P['rr_min']:
        return None
    return (direction, entry, sl, tp1, tp2)


def sim(ind, i, setup, lookahead):
    direction, entry, sl, tp1, tp2 = setup
    n = len(CANDLES_CUR)
    filled = False; booked = 0.0; stop = sl
    for j in range(i + 1, min(i + lookahead, n)):
        jh = CANDLES_CUR[j]['h']; jl = CANDLES_CUR[j]['l']
        if direction == 'buy':
            if not filled and jh >= tp1:
                booked = 0.5 * (tp1 - entry); filled = True; stop = entry
            if filled and jh >= tp2:
                return booked + 0.5 * (tp2 - entry)
            if jl <= stop:
                return -(entry - stop) if not filled else booked + 0.5 * (stop - entry)
        else:
            if not filled and jl <= tp1:
                booked = 0.5 * (entry - tp1); filled = True; stop = entry
            if filled and jl <= tp2:
                return booked + 0.5 * (entry - tp2)
            if jh >= stop:
                return -(stop - entry) if not filled else booked + 0.5 * (entry - stop)
    return booked if filled else None


def backtest(tf, P):
    global CANDLES_CUR
    CANDLES_CUR = CANDLES[tf]
    ind = IND[tf]
    n = len(CANDLES_CUR)
    la = {'M5': 288, 'M15': 96, 'M30': 48}[tf]   # ~24h
    trades = []
    day_h = defaultdict(lambda: -99)
    for i in range(260, n):
        ts = CANDLES_CUR[i]['t']
        dt = datetime.datetime.utcfromtimestamp(ts)
        day = dt.strftime('%Y-%m-%d')
        if dt.hour - day_h[day] < 2:
            continue
        setup = sig_at(ind, i, P)
        if setup is None:
            continue
        pnl = sim(ind, i, setup, la)
        if pnl is None:
            continue
        trades.append({'date': day, 'pnl': round(pnl, 2)})
        day_h[day] = dt.hour
    return trades


def m(trades):
    if not trades:
        return (0, 0.0, 0.0, 0.0)
    nn = len(trades)
    gw = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in trades if t['pnl'] <= 0)) or 1e-9
    wr = 100.0 * sum(1 for t in trades if t['pnl'] > 0) / nn
    return (nn, round(wr, 1), round(gw / gl, 3), round(sum(t['pnl'] for t in trades), 1))


def split(trades):
    if not trades:
        return [], []
    dates = sorted(t['date'] for t in trades)
    cut = dates[int(len(dates) * 0.8)]
    return [t for t in trades if t['date'] < cut], [t for t in trades if t['date'] >= cut]


GRID = {
    'band':      [0.25],
    'htf':       ['none', 'ema200', 'ema50_200'],
    'sl_atr_k':  [1.0, 1.5, 2.0],
    'tp1':       ['r1', 'fib500'],
    'tp2_r':     [2.0, 3.0],
    'rr_min':    [1.0],
}


def main():
    load_data()
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]
    print(f"\n{len(combos)} combo x 3 TF\n")
    hdr = f"{'TF':<4} {'htf':<11} {'k':<4} {'tp1':<7} {'tp2R':<5} | {'IS n/wr/pf/pnl':<26} | {'OOS n/wr/pf/pnl':<26}"
    print(hdr); print('-' * len(hdr))
    winners = []
    for P in combos:
        for tf in ['M5', 'M15', 'M30']:
            tr = backtest(tf, P)
            it, ot = split(tr)
            i_n, i_wr, i_pf, i_pnl = m(it)
            o_n, o_wr, o_pf, o_pnl = m(ot)
            print(f"{tf:<4} {P['htf']:<11} {P['sl_atr_k']:<4} {P['tp1']:<7} {P['tp2_r']:<5} | "
                  f"{i_n:>4}/{i_wr:>4}/{i_pf:>6}/{i_pnl:>8} | {o_n:>4}/{o_wr:>4}/{o_pf:>6}/{o_pnl:>8}")
            if i_pf >= 1.15 and o_pf >= 1.2 and o_n >= 10 and i_n >= 30:
                winners.append((tf, dict(P), (i_n, i_wr, i_pf, i_pnl), (o_n, o_wr, o_pf, o_pnl)))
    print("\n=== CANDIDATI (IS PF>=1.15, OOS PF>=1.2, N sufficiente) ===")
    if not winners:
        print("  nessuno")
    for tf, P, isr, oosr in winners:
        print(f"  {tf} {P} | IS {isr} | OOS {oosr}")


if __name__ == '__main__':
    main()
