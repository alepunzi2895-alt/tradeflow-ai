#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Backtest harness delle strategie dai layout XAU_M15 / XAU_M30 /
XAU_H1_Volumes (2026-09-10).

Gira ESATTAMENTE il codice di produzione (signals.s3?_scan / s3?_manage_step) —
nessuna logica duplicata (regola CLAUDE.md). Modellato su layout_smart.py::
evaluate_ls_frozen.

  ev = evaluate_s3x('S32', tf='M5', P={...override di signals.S32_PARAMS...})
  ev = evaluate_s3x('S33', tf='M30')
  ev = evaluate_s3x('S34', tf='H1', P={'use_session_profile': False})

`ev` è compatibile con opt_harness (is_promotable / dsr_check / pbo_check).

CLI:
  python layout_s3x.py                 # baseline dei 3 sui TF dei layout
  python layout_s3x.py S33 M30         # solo uno

────────────────────────────────────────────────────────────────────────────────
VERDETTO 2026-09-10 (dopo ~195 trial + gate regime ADX, num_trials cumulativo 1687)

  S32_ORDERFLOW_SCALP  (XAU_M15) — NESSUN edge meccanico. 2 modelli provati
    (pullback-to-OB/FVG e liquidity-sweep-reversal), 4 TF (M5/M15/M30/H1): PF < 1
    o n<20. La "ICT Institutional Order Flow" non è replicabile in modo meccanico
    con OB/FVG proxy. → SOLO score in dashboard.

  S33_TREND_MOMENTUM   (XAU_M30→H1) — di superficie buono (full PF 1.72, 4/4 fold+,
    holdout PF 1.59, per-anno tutti +), MA **PBO = 1.00** (max overfit) e DSR
    p-value 0.000 @1687 trial. Il gate ADX che "sistemava" il 2025 era esso stesso
    curve-fit. → SOLO score in dashboard (no capitale).

  S34_VOLUME_AUCTION   (XAU_H1_Volumes) — full PF 2.16 ma fold 2 PF 0.13, n=36
    (1.5/mese, troppo sottile), **PBO = 0.93**, holdout troppo corto per DSR.
    → SOLO score in dashboard (no capitale).

  Confronto: S31_LAYOUT_SMART shippato con PBO 0.33. S32/33/34 stanno a 0.93-1.00.
  Coerente col dead-end da 1500 trial della sessione precedente e con
  directives/07_self_learning_log.md ("edge decaduto, NON tuning").

────────────────────────────────────────────────────────────────────────────────
TEST 2 (2026-09-10, richiesta utente: "usa l'intelligenza — confidence score, news,
RiskGuardian, e le info dai PDF") — `evaluate_s3x(..., system={})`:

  Stack applicato (fattori FISSI dal curriculum ECABS, NON tunati — layout_confidence.py):
  confidence 0-100 = MTF bias (H4 EMA200) + struttura BOS/CHoCH (market_structure.py, gap
  G1) + oscillatore alla zona + premium/discount + sessione + candela reale (regola terzi)
  + regime ADX + proxy-news (spike ATR: nessun dataset news storico) ⇒ gate (skip < 58)
  + sizing per tier + circuit breaker (4 SL → stop 48 barre) + weekly-DD cap.

  S32 (M5)  : nudo PF 0.60 → stack PF 0.62.  Nessun effetto — morta.
  S33 (H1)  : nudo PF 1.72 / PBO 1.00 → stack PF 1.71, holdout 1.58→2.06, per-anno meno
              concentrato, **PBO 1.00 → 0.80**. MEGLIO ma resta overfit: knife-edge sul
              conf_gate (58 ok · 62 → 2026 negativo), DSR p=5.7e-45 @1729 trial. NON promuovibile.
  S34 (H1)  : nudo PF 2.30 / PBO 0.93 → stack PF 2.06, n 37→24, holdout 5.53→1.69, fold
              3/4→2/4. Il gate RIMUOVE vincitori ⇒ conferma che è rumore.

  VERDETTO: il sistema intelligente NON le rende profittevoli. Sharpa S33 al margine
  (l'unica con un battito) ma niente supera la barra.

TEST 3 (2026-09-10, richiesta utente: "se usiamo l'intelligenza per le ENTRY aumenta la
profittabilità?") — `confidence_edge_test()`: genera i candidati con parametri LARGHI
(~3000 setup totali), per ognuno confidence + esito trade, poi decile di confidence vs P&L.

  S32 M5  : Spearman(conf, pnl) = -0.001  (p 0.97)  — ZERO potere predittivo
  S33 M30 : Spearman = +0.021  (p 0.50)   — ZERO. Bucket conf-BASSO (Q1) = il migliore (+$1158)
  S34 H1  : Spearman = -0.023  (p 0.62)   — ZERO. Idem, relazione se mai INVERTITA

  RISPOSTA DEFINITIVA: NO. Il confidence score — pur costruito da concetti di trading veri
  (MTF, BOS/CHoCH, oscillatori, premium/discount, sessione, candele) — NON separa le entry
  buone dalle cattive su questi segnali. Non c'è edge da selezionare. Il miglioramento
  apparente di S33 nel TEST 2 (PBO 1.00→0.80) era fortuna sul valore specifico del gate,
  non potere selettivo reale.

  Le 3 restano come readout di CONTESTO in dashboard (quali fattori sono allineati ADESSO —
  utile per il trading discrezionale) ma il numero NON predice l'esito. Il bot non apre
  ordini. Sottoprodotti tenuti: `market_structure.py` (BOS/CHoCH, gap G1), `layout_confidence.py`
  (fattori riusabili per S31/S16 — lì da RI-validare, potrebbero funzionare su un segnale con edge).
────────────────────────────────────────────────────────────────────────────────
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
        spec = importlib.util.spec_from_file_location('se2_s3x', os.path.join(HERE, 'strategy-engine-v2.py'))
        m = importlib.util.module_from_spec(spec)
        saved = sys.argv
        sys.argv = ['x']
        try:
            spec.loader.exec_module(m)
        finally:
            sys.argv = saved
            try:
                if sys.stdout is not _real:
                    sys.stdout.detach()
            except Exception:
                pass
            sys.stdout = _real
        _SE2 = m
    return _SE2


DATA = {tf: os.path.join(HERE, '..', 'data', f'xauusd_{tf.lower()}_mt5.json')
        for tf in ('M5', 'M15', 'M30', 'H1', 'H4')}
LIVE_WINDOW = ('2026-04-14', '2026-07-10')
# lookahead (barre max in trade) per TF — coerente con run_one dell'engine
TF_LOOKAHEAD = {'M5': 360, 'M15': 160, 'M30': 90, 'H1': 48, 'H4': 24}

_CACHE = {}


def _prep(tf):
    if tf in _CACHE:
        return _CACHE[tf]
    se2 = SE2()
    candles, _ = se2.load_from_file(DATA[tf])
    ind = se2.compute_all(candles)
    n = len(candles)
    O = np.array([c['o'] for c in candles]); H = np.array([c['h'] for c in candles])
    L = np.array([c['l'] for c in candles]); C = np.array([c['c'] for c in candles])
    T = np.array([c['t'] for c in candles], np.int64)
    _CACHE[tf] = (candles, ind, O, H, L, C, T, n)
    return _CACHE[tf]


# ── strategie registrate ─────────────────────────────────────────────────────
SPECS = {
    'S32': dict(tf='M5',  tag='S32_ORDERFLOW_SCALP'),
    'S33': dict(tf='M30', tag='S33_TREND_MOMENTUM'),
    'S34': dict(tf='H1',  tag='S34_VOLUME_AUCTION'),
}


def _get_i(ind, key, i):
    a = ind.get(key)
    if a is None or i >= len(a):
        return None
    return a[i]


_HTF_OF = {'M5': 'H1', 'M15': 'H1', 'M30': 'H4', 'H1': 'H4', 'H4': 'H4'}
_SYS_CACHE = {}


def _prep_system(tf):
    """Array extra per il test 'full stack': market structure (BOS/CHoCH), bias HTF,
    swing high/low. Cache per TF."""
    if tf in _SYS_CACHE:
        return _SYS_CACHE[tf]
    se2 = SE2()
    candles, ind, O, H, L, C, T, n = _prep(tf)
    import market_structure as MS
    from telegram_key_levels import swing_points
    ms = MS.structure_arrays(candles, wing=3)
    sh, sl = swing_points(H, L, wing=3)

    # bias HTF: EMA200 sul TF superiore, riportata barra-per-barra (causale, forward-fill)
    htf = _HTF_OF.get(tf, 'H4')
    hbias = np.zeros(n)
    try:
        hc, _ = se2.load_from_file(DATA[htf])
        he = se2.ema([x['c'] for x in hc], 200)
        ht = np.array([x['t'] for x in hc], np.int64)
        hb_at = np.zeros(len(hc))
        for k in range(len(hc)):
            if k >= 210 and he[k] is not None and he[k - 6] is not None:
                up = hc[k]['c'] > he[k] and he[k] > he[k - 6]
                dn = hc[k]['c'] < he[k] and he[k] < he[k - 6]
                hb_at[k] = 1 if up else (-1 if dn else 0)
        j = 0
        for i in range(n):
            while j + 1 < len(ht) and ht[j + 1] <= T[i]:
                j += 1
            hbias[i] = hb_at[j] if ht[j] <= T[i] else 0
    except Exception:
        pass
    _SYS_CACHE[tf] = (ms, sh, sl, hbias)
    return _SYS_CACHE[tf]


DEFAULT_SYSTEM = dict(
    conf_gate=58,          # salta il setup se confidence < gate
    use_sizing=True,       # lotto scalato per tier di confidence (CONF_TIERS)
    cb_consec_sl=4,        # circuit breaker: dopo N SL consecutivi...
    cb_halt_bars=48,       # ...niente ingressi per M barre
    weekly_dd_cap=250.0,   # se la DD della settimana corrente supera $X (a lotto base) -> stop settimana
)


def evaluate_s3x(strat, tf=None, P=None, folds=4, cooldown_bars=None, system=None):
    """Backtest realistico + walk-forward + holdout + finestra live, via signals.py.
    system: None -> segnale nudo. dict -> applica confidence-gate + sizing + circuit
    breaker + weekly-DD cap (merge su DEFAULT_SYSTEM). Vedi layout_confidence.py."""
    import signals as SIG
    se2 = SE2()
    strat = strat.upper()
    spec_meta = SPECS[strat]
    tf = tf or spec_meta['tf']
    candles, ind, O, H, L, C, T, n = _prep(tf)

    base_params = {'S32': SIG.S32_PARAMS, 'S33': SIG.S33_PARAMS, 'S34': SIG.S34_PARAMS}[strat]
    PP = dict(base_params)
    if P:
        PP.update(P)
    cd = cooldown_bars if cooldown_bars is not None else PP.get('cooldown_bars', 3)
    la = TF_LOOKAHEAD[tf]

    SYS = None
    if system is not None:
        SYS = dict(DEFAULT_SYSTEM); SYS.update(system)
        import layout_confidence as LC
        ms_a, sh_a, sl_a, hbias = _prep_system(tf)
        status_fn = {'S32': SIG.s32_status, 'S33': SIG.s33_status, 'S34': SIG.s34_status}[strat]
        status_P = PP
        _consec_sl = 0
        _halt_until = -1
        _wk = None; _wk_peak = 0.0; _wk_eq = 0.0; _wk_blocked = False

    scan = {'S32': SIG.s32_scan, 'S33': SIG.s33_scan, 'S34': SIG.s34_scan}[strat]
    e20 = ind.get('e20')
    trades = []
    state = {}
    pos = None
    last_exit = -10 ** 9

    for i in range(320, n - 2):
        atr_i = _get_i(ind, 'atr', i)
        if pos is not None:
            jh, jl, jc = H[i], L[i], C[i]
            if strat == 'S32':
                cp_, ek = SIG.s32_manage_step(pos, jh, jl, jc,
                                              e20[i] if e20 else None, atr_i, PP)
            elif strat == 'S33':
                ind_i = {'st': _get_i(ind, 'st', i), 'jaw': _get_i(ind, 'jaw', i),
                         'teeth': _get_i(ind, 'teeth', i), 'lips': _get_i(ind, 'lips', i)}
                cp_, ek = SIG.s33_manage_step(pos, jh, jl, jc, ind_i, atr_i, PP)
            else:
                lb = 5
                sl_lo = float(np.min(L[max(0, i - lb):i + 1]))
                sl_hi = float(np.max(H[max(0, i - lb):i + 1]))
                cp_, ek = SIG.s34_manage_step(pos, jh, jl, jc, sl_lo, sl_hi, atr_i, PP)
            if cp_ is None and (i - pos['ebar']) >= la:
                cp_, ek = jc, 'maxbars'
            if cp_ is not None:
                d = pos['dir']
                move = (cp_ - pos['entry']) if d == 'buy' else (pos['entry'] - cp_)
                rem = (1.0 - PP.get('tp1_frac', 0.5)) if pos['part'] else 1.0
                base_pnl = pos['booked'] + rem * move - se2.trade_cost(ek == 'sl')
                lot_mult = pos.get('lot_mult', 1.0)
                pnl = base_pnl * lot_mult
                tr = {'date': pos['date'], 'hour': pos['hour'], 'dir': d,
                      'entry': pos['entry'], 'outcome': 'win' if pnl > 0 else 'loss',
                      'pnl': round(pnl, 2), 'exit': ek}
                if SYS is not None:
                    tr['conf'] = pos.get('conf'); tr['tier'] = pos.get('tier'); tr['lot_mult'] = lot_mult
                    _consec_sl = _consec_sl + 1 if base_pnl <= 0 else 0
                    if _consec_sl >= SYS['cb_consec_sl']:
                        _halt_until = i + SYS['cb_halt_bars']; _consec_sl = 0
                    _wk_eq += base_pnl
                    _wk_peak = max(_wk_peak, _wk_eq)
                    if (_wk_peak - _wk_eq) > SYS['weekly_dd_cap']:
                        _wk_blocked = True
                trades.append(tr)
                pos = None
                last_exit = i
            continue

        if i - last_exit < cd:
            continue
        if not (np.isfinite(atr_i or np.nan) and (atr_i or 0) > 0):
            continue
        dt = datetime.datetime.utcfromtimestamp(int(T[i]))

        lot_mult = 1.0; conf = None; tier_lbl = None
        if SYS is not None:
            if i <= _halt_until:                       # circuit breaker attivo
                continue
            wk = dt.isocalendar()[:2]
            if wk != _wk:
                _wk = wk; _wk_peak = _wk_eq; _wk_blocked = False
            if _wk_blocked:
                continue

        sp = scan(ind, i, state, dt=dt, P=PP)
        if sp is None:
            continue
        entry = candles[i + 1]['o']
        d = sp['dir']; sgn = 1 if d == 'buy' else -1
        sl = sp['sl']
        risk = abs(entry - sl)
        if risk <= 0 or risk > PP['stop_max'] * atr_i:
            continue
        tp1 = entry + sgn * risk * PP['tp1_r']
        tp2 = sp['tp2']
        if not ((d == 'buy' and entry < tp1 <= tp2) or (d == 'sell' and entry > tp1 >= tp2)):
            tp2 = entry + sgn * risk * PP['tp2_r']

        if SYS is not None:
            ind['_hour'] = dt.hour
            try:
                ssc = status_fn(ind, i, state if isinstance(state, dict) else {},
                                in_position=False, P=status_P).get('score')
            except Exception:
                ssc = None
            conf, _factors = LC.setup_confidence(
                ind, i, d, strat, ms=ms_a, htf_bias=hbias, status_score=ssc,
                swing_hi=sh_a, swing_lo=sl_a)
            ind.pop('_hour', None)
            if conf < SYS['conf_gate']:
                continue
            t = LC.conf_tier(conf)
            tier_lbl = t['label']
            if t['lot'] <= 0:
                continue
            lot_mult = t['lot'] if SYS['use_sizing'] else 1.0

        pos = {'dir': d, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk,
               'part': False, 'booked': 0.0, 'hh': entry, 'll': entry, 'ebar': i + 1,
               'date': dt.strftime('%Y-%m-%d'), 'hour': dt.hour,
               'lot_mult': lot_mult, 'conf': None if conf is None else round(conf, 1), 'tier': tier_lbl}

    wf = se2.walk_forward_report(trades, folds=folds, holdout_frac=0.2)
    lo, hi = LIVE_WINDOW
    live = se2.stats([t for t in trades if lo <= t['date'] <= hi])
    return {'full': wf['full'] if wf else se2.stats(trades), 'folds': wf['folds'] if wf else [],
            'holdout': wf['holdout'] if wf else se2.stats([]),
            'holdout_start': wf['holdout_start'] if wf else None,
            'live': live, 'n_trades': len(trades), 'trades': trades}


# parametri LARGHI: generano molti più candidati -> test del potere selettivo del confidence
LOOSE_P = {
    'S32': dict(sweep_lb=10, sweep_pen=0.02, reclaim_max=2.5, require_ribbon=False,
                obv_confirm=False, cooldown_bars=2, stop_max=3.2),
    'S33': dict(mouth_min=0.02, pullback_atr=2.5, mom_needed=1, adx_min=None,
                session=(0, 24), cooldown_bars=2, stop_max=3.6),
    'S34': dict(edge_tol=0.7, reject_wick=0.10, rvol_min=1.0, adx_max=None,
                min_va_width_atr=0.6, cooldown_bars=2, stop_max=3.4),
}


def confidence_edge_test(strat, tf=None, bins=5):
    """Test diretto: 'l'intelligenza sulle ENTRY aumenta la profittabilità?'
    Genera i candidati con parametri LARGHI, per ognuno calcola il confidence score e
    l'esito del trade (stessa gestione TP1/BE/trail). Poi raggruppa per decile/quintile
    di confidence e guarda WR / P&L medio / PF per bucket. Se il confidence ha potere
    predittivo i bucket alti battono i bassi in modo monotòno."""
    import signals as SIG
    import layout_confidence as LC
    import numpy as np
    from scipy.stats import spearmanr
    se2 = SE2()
    strat = strat.upper()
    tf = tf or SPECS[strat]['tf']
    candles, ind, O, H, L, C, T, n = _prep(tf)
    ms_a, sh_a, sl_a, hbias = _prep_system(tf)
    base = {'S32': SIG.S32_PARAMS, 'S33': SIG.S33_PARAMS, 'S34': SIG.S34_PARAMS}[strat]
    PP = dict(base); PP.update(LOOSE_P[strat])
    scan = {'S32': SIG.s32_scan, 'S33': SIG.s33_scan, 'S34': SIG.s34_scan}[strat]
    status_fn = {'S32': SIG.s32_status, 'S33': SIG.s33_status, 'S34': SIG.s34_status}[strat]
    mstep = {'S32': SIG.s32_manage_step, 'S33': SIG.s33_manage_step, 'S34': SIG.s34_manage_step}[strat]
    la = TF_LOOKAHEAD[tf]; e20 = ind.get('e20')
    rows = []
    state = {}
    i = 320
    while i < n - 2:
        atr_i = _get_i(ind, 'atr', i)
        if not (np.isfinite(atr_i or np.nan) and (atr_i or 0) > 0):
            i += 1; continue
        dt = datetime.datetime.utcfromtimestamp(int(T[i]))
        sp = scan(ind, i, state, dt=dt, P=PP)
        if sp is None:
            i += 1; continue
        d = sp['dir']; sgn = 1 if d == 'buy' else -1
        entry = candles[i + 1]['o']
        sl = sp['sl']; risk = abs(entry - sl)
        if risk <= 0 or risk > PP['stop_max'] * atr_i:
            i += 1; continue
        tp1 = entry + sgn * risk * PP['tp1_r']
        tp2 = sp['tp2']
        if not ((d == 'buy' and entry < tp1 <= tp2) or (d == 'sell' and entry > tp1 >= tp2)):
            tp2 = entry + sgn * risk * PP['tp2_r']
        ind['_hour'] = dt.hour
        try:
            ssc = status_fn(ind, i, {}, in_position=False, P=PP).get('score')
        except Exception:
            ssc = None
        conf, _f = LC.setup_confidence(ind, i, d, strat, ms=ms_a, htf_bias=hbias,
                                       status_score=ssc, swing_hi=sh_a, swing_lo=sl_a)
        ind.pop('_hour', None)
        pos = {'dir': d, 'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'risk': risk,
               'part': False, 'booked': 0.0, 'hh': entry, 'll': entry, 'ebar': i + 1}
        pnl = None
        for j in range(i + 1, min(i + 1 + la, n)):
            jh, jl, jc = H[j], L[j], C[j]
            if strat == 'S32':
                cp_, ek = mstep(pos, jh, jl, jc, e20[j] if e20 else None, _get_i(ind, 'atr', j), PP)
            elif strat == 'S33':
                ii = {'st': _get_i(ind, 'st', j), 'jaw': _get_i(ind, 'jaw', j),
                      'teeth': _get_i(ind, 'teeth', j), 'lips': _get_i(ind, 'lips', j)}
                cp_, ek = mstep(pos, jh, jl, jc, ii, _get_i(ind, 'atr', j), PP)
            else:
                lb = 5
                cp_, ek = mstep(pos, jh, jl, jc, float(np.min(L[max(0, j - lb):j + 1])),
                                float(np.max(H[max(0, j - lb):j + 1])), _get_i(ind, 'atr', j), PP)
            if cp_ is None and (j - pos['ebar']) >= la:
                cp_, ek = jc, 'maxbars'
            if cp_ is not None:
                mv = (cp_ - entry) if d == 'buy' else (entry - cp_)
                rem = (1.0 - PP.get('tp1_frac', 0.5)) if pos['part'] else 1.0
                pnl = pos['booked'] + rem * mv - se2.trade_cost(ek == 'sl')
                i = j
                break
        if pnl is None:
            i += 1; continue
        rows.append((conf, pnl))
        i += 1

    if len(rows) < 40:
        print(f"{strat} {tf}: solo {len(rows)} candidati — insufficiente"); return
    confs = np.array([r[0] for r in rows]); pnls = np.array([r[1] for r in rows])
    rho, p = spearmanr(confs, pnls)
    order = np.argsort(confs)
    print(f"\n=== {strat} {tf} · CONFIDENCE vs ESITO ENTRY ({len(rows)} candidati, param larghi) ===")
    print(f"  Spearman(confidence, pnl) = {rho:+.3f}  (p={p:.3f})   "
          f"{'← predittivo' if p < 0.05 and rho > 0.1 else '← nessun potere predittivo'}")
    q = np.array_split(order, bins)
    print(f"  {'bucket':<8}{'conf range':<14}{'n':>4}{'WR':>7}{'pnl medio':>11}{'PF':>7}{'pnl tot':>10}")
    for k, idxs in enumerate(q):
        cs = confs[idxs]; ps = pnls[idxs]
        wr = 100 * (ps > 0).mean()
        gw = ps[ps > 0].sum(); gl = -ps[ps <= 0].sum() or 1e-9
        print(f"  Q{k+1:<7}{cs.min():.0f}-{cs.max():<10.0f}{len(idxs):>4}{wr:>6.0f}%"
              f"{ps.mean():>11.2f}{gw/gl:>7.2f}{ps.sum():>10.0f}")
    top = pnls[order[-len(order)//bins:]]; bot = pnls[order[:len(order)//bins]]
    print(f"  top-quintile pnl tot {top.sum():+.0f}  vs  bottom-quintile {bot.sum():+.0f}  "
          f"(Δ {top.sum()-bot.sum():+.0f})")


if __name__ == '__main__':
    import warnings; warnings.filterwarnings('ignore')
    import opt_harness as OH
    args = [a.upper() for a in sys.argv[1:]]
    if args and args[0] == 'EDGE':
        for s in (['S32', 'S33', 'S34'] if len(args) < 2 else [args[1]]):
            confidence_edge_test(s, SPECS[s]['tf'] if len(args) < 3 else args[2])
        sys.exit(0)
    combos = ([(args[0], args[1] if len(args) > 1 else SPECS[args[0]]['tf'])]
              if args else [(s, SPECS[s]['tf']) for s in SPECS])
    for strat, tf in combos:
        OH.print_eval(f"{strat} {tf} · NUDO", evaluate_s3x(strat, tf), num_trials=1)
        OH.print_eval(f"{strat} {tf} · FULL STACK (confidence + news-proxy + circuit breaker + sizing)",
                      evaluate_s3x(strat, tf, system={}), num_trials=1)
