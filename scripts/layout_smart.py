#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Strategia "smart" dai layout XAU: BREAK → RETEST @ CONFLUENZA (2026-09-10)
════════════════════════════════════════════════════════════════════════════════════════
SOLO RICERCA. Codifica il modo in cui questi indicatori sono usati DAVVERO (non "compra
ogni rottura"):

  1. REGIME  — solo in trend pulito: EMA200 in pendenza (slope ≥ k·ATR su N barre) e
               prezzo dal lato giusto. In range non si opera.
  2. TRIGGER — rottura di trendline LuxAlgo (stretta) nella direzione del trend →
               si memorizza il livello rotto L_break, non si entra subito.
  3. RETEST  — nelle K barre successive il prezzo torna su L_break / su una ZONA DI
               CONFLUENZA vicina (≥ min_lv livelli tra Fib pivot, PDH/PDL/PWH/PWL,
               H/L sessioni, prev-4H, EMA200, trendline, entro band·ATR).
  4. ENTRY   — candela di rifiuto alla zona (mecca ≥ w·ATR, chiusura ricentrata).
  5. STOP    — strutturale: oltre la zona / lo swing del rifiuto (cap a stop_max·ATR).
  6. TARGET  — TP1 = prossima zona di confluenza (parziale 50%), poi BE, poi trailing
               (swing / trendline / ATR). Runner fino alla zona dopo o time-stop.
  Sessione London+NY, niente venerdì pomeriggio.

`evaluate_smart(tf, **params)` → dict `ev` compatibile con opt_harness.
"""
import os, sys, importlib.util, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_SE2 = None
def SE2():
    global _SE2
    if _SE2 is None:
        _real = sys.stdout
        spec = importlib.util.spec_from_file_location('se2_smart', os.path.join(HERE, 'strategy-engine-v2.py'))
        m = importlib.util.module_from_spec(spec); saved = sys.argv; sys.argv = ['x']
        try:
            spec.loader.exec_module(m)
        finally:
            sys.argv = saved
            try:
                if sys.stdout is not _real: sys.stdout.detach()
            except Exception: pass
            sys.stdout = _real
        _SE2 = m
    return _SE2

DATA = {tf: os.path.join(HERE, '..', 'data', f'xauusd_{tf.lower()}_mt5.json') for tf in ('M15','M30','H1','H4')}
LIVE_WINDOW = ('2026-04-14', '2026-07-10')
TF_LOOKAHEAD = {'M15': 160, 'M30': 90, 'H1': 48, 'H4': 24}

LEVEL_KEYS = ['dpiv','dr1','dr2','dr3','ds1','ds2','ds3','pdh','pdl','pwh','pwl','ema200',
              'sess_asia_hi','sess_asia_lo','sess_lon_hi','sess_lon_lo','sess_ny_hi','sess_ny_lo',
              'p4h_hi','p4h_lo','day_open','tlb_upper','tlb_lower']

_CACHE = {}
def _prep(tf):
    if tf in _CACHE:
        return _CACHE[tf]
    se2 = SE2()
    candles, _ = se2.load_from_file(DATA[tf])
    ind = se2.compute_all(candles)
    n = len(candles)
    A = {k: np.array([(ind[k][i] if ind.get(k) and ind[k][i] is not None else np.nan)
                      for i in range(n)], float) for k in set(LEVEL_KEYS + ['adx'])}
    atr = np.array([ind['atr'][i] or np.nan for i in range(n)])
    O = np.array([c['o'] for c in candles]); H = np.array([c['h'] for c in candles])
    L = np.array([c['l'] for c in candles]); C = np.array([c['c'] for c in candles])
    T = np.array([c['t'] for c in candles], np.int64)
    V = np.array([c.get('v', 0) for c in candles], float)
    vsma = np.convolve(V, np.ones(20) / 20, mode='full')[:n]
    vsma[:20] = np.nan
    vol_ratio = np.divide(V, vsma, out=np.full(n, np.nan), where=vsma > 0)
    A['vol_ratio'] = vol_ratio
    _CACHE[tf] = (candles, ind, A, atr, O, H, L, C, T, n)
    return _CACHE[tf]


DEFAULTS = dict(
    slope_bars=10, slope_min=0.12, require_price_side=True, adx_min=0,
    retest_min=1, retest_max=14,
    band=0.40, min_lv=2, retest_tol=0.35,
    reject_wick=0.20,
    stop_buf=0.25, stop_max=2.6, min_risk_atr=0.25,
    tp1_mode='zone', tp1_r=1.5, tp1_frac=0.5,
    be_off=0.05, trail='swing', trail_give=1.0, trail_swing_lb=5,
    tp2_mode='zone', tp2_r=3.0, time_stop=0,
    session=(7, 21), no_friday_pm=True, cooldown_bars=3,
    vol_min=0.0,   # >0 → la candela di rifiuto deve avere volume ≥ vol_min × media20 (layout Volumes)
)


def _zones(A, i, atrv, band, min_lv):
    lv = sorted(v for k in LEVEL_KEYS for v in (A[k][i],) if np.isfinite(v))
    if not lv:
        return []
    out = []; cur = [lv[0]]; bw = band * atrv
    for x in lv[1:]:
        if x - cur[-1] <= bw:
            cur.append(x)
        else:
            if len(cur) >= min_lv:
                out.append((cur[0], cur[-1], len(cur), sum(cur) / len(cur)))
            cur = [x]
    if len(cur) >= min_lv:
        out.append((cur[0], cur[-1], len(cur), sum(cur) / len(cur)))
    return out


def evaluate_smart(tf, folds=4, **params):
    P = dict(DEFAULTS); P.update(params)
    se2 = SE2()
    candles, ind, A, atr, O, H, L, C, T, n = _prep(tf)
    la = TF_LOOKAHEAD[tf]
    trades = []
    pending = None          # {'dir','L','start','exp'}
    pos = None
    last_exit_bar = -10 ** 9

    for i in range(300, n - 2):
        av = atr[i]
        if not np.isfinite(av) or av <= 0:
            continue
        dt = datetime.datetime.utcfromtimestamp(int(T[i]))

        # ── gestione posizione aperta ──
        if pos is not None:
            d = pos['dir']; entry = pos['entry']; risk = pos['risk']
            jh, jl, jc = H[i], L[i], C[i]
            pos['hh'] = max(pos['hh'], jh); pos['ll'] = min(pos['ll'], jl)
            profit = (jc - entry) if d == 'buy' else (entry - jc)

            if not pos['part']:
                hit = (jh >= pos['tp1']) if d == 'buy' else (jl <= pos['tp1'])
                if hit:
                    move1 = (pos['tp1'] - entry) if d == 'buy' else (entry - pos['tp1'])
                    pos['booked'] += P['tp1_frac'] * move1
                    pos['part'] = True
                    be = entry + P['be_off'] * av if d == 'buy' else entry - P['be_off'] * av
                    pos['sl'] = max(pos['sl'], be) if d == 'buy' else min(pos['sl'], be)
            if pos['part']:
                if P['trail'] == 'swing':
                    lb = P['trail_swing_lb']
                    cand = np.min(L[max(0, i - lb):i + 1]) if d == 'buy' else np.max(H[max(0, i - lb):i + 1])
                elif P['trail'] == 'trendline':
                    cand = A['tlb_lower'][i] if d == 'buy' else A['tlb_upper'][i]
                else:  # atr
                    cand = jc - P['trail_give'] * av if d == 'buy' else jc + P['trail_give'] * av
                if np.isfinite(cand):
                    pos['sl'] = max(pos['sl'], cand) if d == 'buy' else min(pos['sl'], cand)

            tp_final = pos.get('tp2')
            res = se2.resolve_intrabar(jh, jl, tp_final if tp_final else (entry + 999 if d == 'buy' else entry - 999),
                                       pos['sl'], d == 'buy')
            exit_kind = None; close_price = None
            if res == 'loss':
                close_price = pos['sl']; exit_kind = 'sl'
            elif res == 'win' and tp_final:
                close_price = tp_final; exit_kind = 'tp2'
            elif P['time_stop'] and (i - pos['ebar']) >= P['time_stop']:
                close_price = jc; exit_kind = 'time'
            elif (i - pos['ebar']) >= la:
                close_price = jc; exit_kind = 'maxbars'
            if close_price is not None:
                move = (close_price - entry) if d == 'buy' else (entry - close_price)
                rem = 1.0 - (P['tp1_frac'] if pos['part'] else 0.0)
                pnl = pos['booked'] + rem * move - se2.trade_cost(exit_kind == 'sl')
                trades.append({'date': pos['date'], 'hour': pos['hour'], 'dir': d, 'entry': entry,
                               'outcome': 'win' if pnl > 0 else 'loss', 'pnl': round(pnl, 2), 'exit': exit_kind})
                pos = None; last_exit_bar = i
            continue

        if i - last_exit_bar < P['cooldown_bars']:
            continue

        # ── regime: trend pulito ──
        e = A['ema200'][i]; ep = A['ema200'][i - P['slope_bars']]
        if not (np.isfinite(e) and np.isfinite(ep)):
            continue
        slope = (e - ep) / av
        up_ok = slope >= P['slope_min'] and (not P['require_price_side'] or C[i] > e)
        dn_ok = slope <= -P['slope_min'] and (not P['require_price_side'] or C[i] < e)
        if P['adx_min'] and np.isfinite(A['adx'][i]) and A['adx'][i] < P['adx_min']:
            up_ok = dn_ok = False

        # ── nuovo break → pending ──
        if up_ok and ind['tlb_up_s'][i]:
            pending = {'dir': 'buy', 'L': A['tlb_upper'][i], 'start': i, 'exp': i + P['retest_max']}
        elif dn_ok and ind['tlb_dn_s'][i]:
            pending = {'dir': 'sell', 'L': A['tlb_lower'][i], 'start': i, 'exp': i + P['retest_max']}

        # ── retest del pending ──
        if pending is not None and pending['start'] + P['retest_min'] <= i <= pending['exp']:
            d = pending['dir']; Lb = pending['L']
            if not np.isfinite(Lb):
                pending = None; continue
            if P['session'] and not (P['session'][0] <= dt.hour < P['session'][1]):
                if i >= pending['exp']:
                    pending = None
                continue
            if P['no_friday_pm'] and dt.weekday() == 4 and dt.hour >= 16:
                continue
            zs = _zones(A, i, av, P['band'], P['min_lv'])
            near = None
            for z in zs:
                if abs(z[3] - Lb) <= P['retest_tol'] * av or (z[0] - P['retest_tol'] * av <= Lb <= z[1] + P['retest_tol'] * av):
                    near = z; break
            if near is None:
                if i >= pending['exp']:
                    pending = None
                continue
            zlo, zhi, zn, zc = near
            if d == 'buy':
                touched = L[i] <= zhi + P['retest_tol'] * av
                wick = min(C[i], O[i]) - L[i]
                reject = C[i] > O[i] and wick >= P['reject_wick'] * av and C[i] > zc
            else:
                touched = H[i] >= zlo - P['retest_tol'] * av
                wick = H[i] - max(C[i], O[i])
                reject = C[i] < O[i] and wick >= P['reject_wick'] * av and C[i] < zc
            if P['vol_min'] > 0:
                vr = A['vol_ratio'][i]
                if not (np.isfinite(vr) and vr >= P['vol_min']):
                    reject = False
            if not (touched and reject):
                if i >= pending['exp']:
                    pending = None
                continue

            entry = candles[i + 1]['o']
            if d == 'buy':
                sl = min(zlo, L[i]) - P['stop_buf'] * av
            else:
                sl = max(zhi, H[i]) + P['stop_buf'] * av
            risk = abs(entry - sl)
            if risk > P['stop_max'] * av or risk < P['min_risk_atr'] * av:
                pending = None; continue

            # TP1 / TP2 = prossime zone di confluenza nella direzione
            fwd = sorted([z for z in zs if (z[3] > entry + 0.4 * av) == (d == 'buy') and z[3] != zc],
                         key=lambda z: z[3], reverse=(d == 'sell'))
            if P['tp1_mode'] == 'zone' and fwd:
                tp1 = fwd[0][3]
            else:
                tp1 = entry + risk * P['tp1_r'] * (1 if d == 'buy' else -1)
            if P['tp2_mode'] == 'zone' and len(fwd) > 1:
                tp2 = fwd[1][3]
            elif P['tp2_mode'] == 'zone' and fwd:
                tp2 = entry + risk * P['tp2_r'] * (1 if d == 'buy' else -1)
            else:
                tp2 = entry + risk * P['tp2_r'] * (1 if d == 'buy' else -1)
            # sanità: tp1 tra entry e tp2
            if (d == 'buy' and not (entry < tp1 <= tp2)) or (d == 'sell' and not (entry > tp1 >= tp2)):
                tp1 = entry + risk * P['tp1_r'] * (1 if d == 'buy' else -1)
                tp2 = entry + risk * P['tp2_r'] * (1 if d == 'buy' else -1)

            pos = {'dir': d, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk,
                   'ebar': i + 1, 'part': False, 'booked': 0.0, 'hh': entry, 'll': entry,
                   'date': dt.strftime('%Y-%m-%d'), 'hour': dt.hour}
            pending = None

        if pending is not None and i > pending['exp']:
            pending = None

    wf = se2.walk_forward_report(trades, folds=folds, holdout_frac=0.2)
    lo, hi = LIVE_WINDOW
    live = se2.stats([t for t in trades if lo <= t['date'] <= hi])
    return {
        'full': wf['full'] if wf else se2.stats(trades),
        'folds': wf['folds'] if wf else [],
        'holdout': wf['holdout'] if wf else se2.stats([]),
        'holdout_start': wf['holdout_start'] if wf else None,
        'live': live, 'n_trades': len(trades), 'trades': trades,
    }


# ── CONFIG CANDIDATA (sprint 2026-09-10, paper-test) ────────────────────────
# H1. Break→retest→confluenza→exit strutturale. Vedi directives/02_strategies.md.
#   full PF 1.99 · +$516/22m @0.01lot · DD $130 · 16/22 mesi+ · holdout PF 1.86 (n10)
#   live-window PF 1.66 · walk-forward 3/4 fold+ · PBO 0.33 (non overfit) · regge cost×2
#   buy n37 WR57% +$281 · sell n16 WR44% +$235 · per-anno 2024:+30 2025:+190 2026:+296
CANDIDATE_H1 = dict(
    slope_min=0.12, retest_max=16, min_lv=2, reject_wick=0.22, band=0.55,
    trail='trendline', stop_max=2.8, tp1_mode='fixed', tp1_r=1.5, tp2_mode='zone',
    session=(7, 21),
)

def evaluate_ls_frozen(tf='H1', P=None, folds=4, cooldown_bars=3):
    """Backtest della config PRODUZIONE via signals.ls_scan / ls_manage_step (stessa
    identica logica del bot — nessuna duplicazione). P = override di signals.LS_PARAMS."""
    import signals as SIG
    se2 = SE2()
    candles, ind, A, atr, O, H, L, C, T, n = _prep(tf)
    PP = dict(SIG.LS_PARAMS)
    if P:
        PP.update(P)
    tlb_low = A['tlb_lower']; tlb_up = A['tlb_upper']; vr = A['vol_ratio']
    trades = []
    state = {'pending': None}
    pos = None
    last_exit = -10 ** 9
    la = TF_LOOKAHEAD[tf]
    for i in range(300, n - 2):
        if pos is not None:
            cp_, ek = SIG.ls_manage_step(pos, H[i], L[i], C[i],
                                         tlb_low[i], tlb_up[i], atr[i], PP)
            if cp_ is None and (i - pos['ebar']) >= la:
                cp_, ek = C[i], 'maxbars'
            if cp_ is not None:
                d = pos['dir']
                move = (cp_ - pos['entry']) if d == 'buy' else (pos['entry'] - cp_)
                rem = 0.5 if pos['part'] else 1.0
                pnl = pos['booked'] + rem * move - se2.trade_cost(ek == 'sl')
                trades.append({'date': pos['date'], 'hour': pos['hour'], 'dir': d,
                               'entry': pos['entry'], 'outcome': 'win' if pnl > 0 else 'loss',
                               'pnl': round(pnl, 2), 'exit': ek})
                pos = None
                last_exit = i
            continue
        if i - last_exit < cooldown_bars:
            continue
        dt = datetime.datetime.utcfromtimestamp(int(T[i]))
        spec = SIG.ls_scan(ind, i, state, dt=dt,
                           vol_ratio=(vr[i] if PP['vol_min'] > 0 else None), P=PP)
        if spec is None:
            continue
        entry = candles[i + 1]['o']
        d = spec['dir']; sgn = 1 if d == 'buy' else -1
        # SL/TP2 restano ai livelli STRUTTURALI (zona), il fill next-open cambia solo R e TP1
        sl = spec['sl']
        risk = abs(entry - sl)
        if risk <= 0 or risk > PP['stop_max'] * (atr[i] or 1e9):
            continue
        tp1 = entry + sgn * risk * PP['tp1_r']
        tp2 = spec['tp2']
        if not ((d == 'buy' and entry < tp1 <= tp2) or (d == 'sell' and entry > tp1 >= tp2)):
            tp2 = entry + sgn * risk * PP['tp2_r']
        pos = {'dir': d, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk,
               'part': False, 'booked': 0.0, 'hh': entry, 'll': entry, 'ebar': i + 1,
               'date': dt.strftime('%Y-%m-%d'), 'hour': dt.hour}
    wf = se2.walk_forward_report(trades, folds=folds, holdout_frac=0.2)
    lo, hi = LIVE_WINDOW
    live = se2.stats([t for t in trades if lo <= t['date'] <= hi])
    return {'full': wf['full'] if wf else se2.stats(trades), 'folds': wf['folds'] if wf else [],
            'holdout': wf['holdout'] if wf else se2.stats([]),
            'holdout_start': wf['holdout_start'] if wf else None,
            'live': live, 'n_trades': len(trades), 'trades': trades}


if __name__ == '__main__':
    import opt_harness as OH
    OH.print_eval("LAYOUT-SMART H1 · evaluate_smart (grid harness)", evaluate_smart('H1', **CANDIDATE_H1))
    OH.print_eval("LAYOUT-SMART H1 · evaluate_ls_frozen (== bot / signals.py core)", evaluate_ls_frozen('H1'))
    for tf in ('M30', 'M15'):
        OH.print_eval(f"LAYOUT-SMART {tf} · ls_frozen (controllo — non promosso)", evaluate_ls_frozen(tf))
