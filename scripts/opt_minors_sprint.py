#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sprint perf-stabile 2026-09-02 — subagent C: S17 / S10 / S09 minor strategies.
Usa opt_harness.evaluate (backtester realistico: cost model, fill pessimistico,
entry next-open, walk-forward + holdout). Holdout PF = metrica primaria.
"""
import sys, os, json, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from opt_harness import evaluate, is_promotable, print_eval, pos_folds
from signals import _get, signal_convergence_scalp, signal_ob_fvg_scalp, signal_mfkk_scalping

OUT = os.path.join(HERE, '..', 'backtests', 'results', 'opt_minors_2026-09-02.json')

# ───────────────────────── FACTORIES (default = signals.py corrente) ──────────

def make_s17(adx_gate=22, bb_hi=0.58, bb_lo=0.42, atr_spike=2.2):
    def fn(ind, i, h1_trend=None, hour=None):
        if i < 89: return None
        e34 = ind['e34'][i]; e89 = ind['e89'][i]
        sk = ind['srsi_k'][i]; sd = ind['srsi_d'][i]
        bbu = ind['bb_up'][i]
        bbl_arr = _get(ind, 'bb_dn', 'bb_lo'); bbl = bbl_arr[i] if bbl_arr else None
        c = ind['C'][i]; e50 = ind['e50'][i]; atr = ind['atr'][i]
        a = ind['adx'][i]
        atr_ref = _get(ind, 'atr_avg', 'atr30'); atr_avg = atr_ref[i] if atr_ref else None
        if None in (e34, e89, sk, sd, bbu, bbl, c, e50, atr): return None
        if atr_avg and atr > atr_spike * atr_avg: return None
        if a is not None and a < adx_gate: return None
        bb_range = bbu - bbl
        bb_pct = (c - bbl) / bb_range if bb_range > 0 else 0.5
        e34_p = ind['e34'][i-1]; e89_p = ind['e89'][i-1]
        sk_p = ind['srsi_k'][i-1]; sd_p = ind['srsi_d'][i-1]
        if None in (e34_p, e89_p, sk_p, sd_p): return None
        bull_prev = e34_p > e89_p and sk_p > sd_p
        bear_prev = e34_p < e89_p and sk_p < sd_p
        bull = e34 > e89 and sk > sd and bb_pct > bb_hi and c > e50 and not bull_prev
        bear = e34 < e89 and sk < sd and bb_pct < bb_lo and c < e50 and not bear_prev
        if bull: return 'buy'
        if bear: return 'sell'
        return None
    return fn


def make_s10(adx_gate=20, atr_spike_mult=2.5, session=(8, 17)):
    def fn(ind, i, h1_trend=None, hour=None):
        if i < 233: return None
        if session is not None and hour is not None and not (session[0] <= hour < session[1]): return None
        ob_b = ind.get('ob_bull'); ob_s = ind.get('ob_bear')
        fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
        e233 = ind['e233'][i]; c = ind['C'][i]
        a = ind.get('adx', [None]*(i+1))[i]
        if ob_b is None or fb is None or e233 is None: return None
        if a is not None and a < adx_gate: return None
        atr_arr = ind.get('atr'); atr_ref = _get(ind, 'atr_avg', 'atr30')
        atr = atr_arr[i] if atr_arr else 0
        atr_avg = atr_ref[i] if atr_ref else 0
        if atr_avg and atr > atr_spike_mult * atr_avg: return None
        if h1_trend is not None and h1_trend != 0:
            if ob_b[i] and fb[i] and h1_trend != -1: return None
            if ob_s[i] and fs[i] and h1_trend != 1: return None
        if ob_b[i] and fb[i] and c > e233: return 'buy'
        if ob_s[i] and fs[i] and c < e233: return 'sell'
        return None
    return fn


def make_s09(adx_gate=20, session=(6, 19), rsi_conf=True, obv_conf=True):
    def fn(ind, i, h1_trend=None, hour=None):
        if i < 233: return None
        if session is not None and hour is not None and not (session[0] <= hour < session[1]): return None
        e13 = ind['e13'][i]; e34 = ind['e34'][i]; e89 = ind['e89'][i]; e233 = ind['e233'][i]
        fb = ind.get('fvg_bull'); fs = ind.get('fvg_bear')
        c = ind['C'][i]
        if None in (e13, e34, e89, e233) or fb is None: return None
        a_arr = ind.get('adx'); a = a_arr[i] if a_arr else None
        if a is not None and a < adx_gate: return None
        r_arr = ind.get('rsi'); r = r_arr[i] if r_arr else None
        obv_arr_s = ind.get('obv'); obv_ema_arr_s = ind.get('obv_ema')
        obv_s = obv_arr_s[i] if obv_arr_s else None
        oe_s = obv_ema_arr_s[i] if obv_ema_arr_s else None
        rsi_bull = (not rsi_conf) or r is None or r > 50
        rsi_bear = (not rsi_conf) or r is None or r < 50
        obv_bull = (not obv_conf) or obv_s is None or oe_s is None or obv_s > oe_s
        obv_bear = (not obv_conf) or obv_s is None or oe_s is None or obv_s < oe_s
        if h1_trend is not None and h1_trend != 0:
            if e13 > e34 > e89 > e233 and h1_trend != -1: return None
            if e13 < e34 < e89 < e233 and h1_trend != 1: return None
        if e13 > e34 > e89 > e233 and c > e233 and fb[i] and rsi_bull and obv_bull: return 'buy'
        if e13 < e34 < e89 < e233 and c < e233 and fs[i] and rsi_bear and obv_bear: return 'sell'
        return None
    return fn


def summ(ev):
    h = ev['holdout']; f = ev['full']
    return {
        'n_trades': ev['n_trades'],
        'full':    {k: f[k] for k in ('n','wr','pf','pnl','dd','tr_day','months')},
        'holdout': {k: h[k] for k in ('n','wr','pf','pnl','dd','months')},
        'holdout_start': ev['holdout_start'],
        'live':    {k: ev['live'][k] for k in ('n','wr','pf','pnl')},
        'pos_folds': f"{pos_folds(ev)}/{len(ev['folds'])}",
    }


RESULT = {}

# ═══════════════════════════ S17_CONVERGENCE_SCALP (H4) ══════════════════════
print("\n" + "#"*90 + "\n# S17_CONVERGENCE_SCALP\n" + "#"*90)
NAME = 'S17_CONVERGENCE_SCALP'
base17 = evaluate(NAME, signal_convergence_scalp, tf='H4', tp_mult=4.0, sl_mult=1.5)
print_eval("S17 BASELINE H4 4.0/1.5", base17)
combos17 = []
grid17 = []
for adx in (19, 22, 25):
    for (hi, lo) in ((0.55, 0.45), (0.58, 0.42), (0.62, 0.38)):
        for spike in (2.0, 2.2, 2.5):
            grid17.append(dict(adx_gate=adx, bb_hi=hi, bb_lo=lo, atr_spike=spike))
for tf, tpm, slm in [('H4', 4.0, 1.5)]:
    pass
best17 = None
for g in grid17:
    for (tpm, slm) in [(4.0,1.5),(3.5,1.5),(4.5,1.5),(4.0,1.25),(4.0,1.75)]:
        fn = make_s17(**g)
        ev = evaluate(NAME, fn, tf='H4', tp_mult=tpm, sl_mult=slm)
        prom, checks = is_promotable(ev, base17)
        rec = {**g, 'tp_mult': tpm, 'sl_mult': slm, 'tf': 'H4',
               'holdout_pf': ev['holdout']['pf'], 'holdout_pnl': ev['holdout']['pnl'],
               'holdout_n': ev['holdout']['n'], 'full_pf': ev['full']['pf'],
               'n_trades': ev['n_trades'], 'pos_folds': pos_folds(ev), 'promotable': prom}
        combos17.append(rec)
        if prom and (best17 is None or ev['holdout']['pf'] > best17[1]['holdout']['pf']):
            best17 = (rec, ev)
# H1 proxy check on baseline params
ev17_h1 = evaluate(NAME, signal_convergence_scalp, tf='H1', tp_mult=4.0, sl_mult=1.5)
print_eval("S17 baseline on H1 (proxy)", ev17_h1)
RESULT['S17_CONVERGENCE_SCALP'] = {
    'primary_tf': 'H4',
    'baseline_ev': summ(base17),
    'baseline_h1_proxy': summ(ev17_h1),
    'callpath_mismatches': [
        "signal_convergence_scalp declares h1_trend/hour params but body never reads h1_trend — bot passes h1_trend=I_h1['st'] (H4 block L2567, StrategySelector L1884) harmlessly; only `hour` is load-bearing and it IS passed in every bot path (H4 L2567, M30 L2424, selector L1884).",
        "bot get_signal (L643) calls fn(I,i) with NO hour — but returns None for non-H1 tf so S17 (H4) never reaches it. Non-issue.",
        "backtester run_one S17 branch (L1018 else) calls fn(ind,i,hour=hour); run_adaptive L1208 passes h1_trend+hour. Consistent with bot.",
    ],
    'combos_tested': combos17,
    'winner': best17[0] if best17 else None,
}

# ═══════════════════════════ S10_OB_FVG_SCALP (M30) ═════════════════════════
print("\n" + "#"*90 + "\n# S10_OB_FVG_SCALP\n" + "#"*90)
NAME = 'S10_OB_FVG_SCALP'
base10 = evaluate(NAME, signal_ob_fvg_scalp, tf='M30', tp_mult=3.5, sl_mult=1.5)
print_eval("S10 BASELINE M30 3.5/1.5", base10)
combos10 = []
best10 = None
sessions = {'8-17': (8,17), '7-19': (7,19), 'none': None}
for adx in (17, 20, 23):
    for spike in (2.0, 2.5, 3.0):
        for sk, sv in sessions.items():
            for (tpm, slm) in [(3.0,1.5),(3.5,1.5),(4.0,1.5),(3.5,1.25),(4.0,1.25)]:
                fn = make_s10(adx_gate=adx, atr_spike_mult=spike, session=sv)
                ev = evaluate(NAME, fn, tf='M30', tp_mult=tpm, sl_mult=slm)
                prom, _ = is_promotable(ev, base10)
                rec = {'adx_gate': adx, 'atr_spike_mult': spike, 'session': sk,
                       'tp_mult': tpm, 'sl_mult': slm,
                       'holdout_pf': ev['holdout']['pf'], 'holdout_pnl': ev['holdout']['pnl'],
                       'holdout_n': ev['holdout']['n'], 'full_pf': ev['full']['pf'],
                       'n_trades': ev['n_trades'], 'pos_folds': pos_folds(ev), 'promotable': prom}
                combos10.append(rec)
                if prom and (best10 is None or ev['holdout']['pf'] > best10[1]['holdout']['pf']):
                    best10 = (rec, ev)
RESULT['S10_OB_FVG_SCALP'] = {
    'primary_tf': 'M30',
    'baseline_ev': summ(base10),
    'callpath_mismatches': [
        "signal_ob_fvg_scalp: bot M30 block L2424 passes h1_trend=curr_h1_trend (H1 Supertrend) + hour — CORRECT since 2026-07-17 fix.",
        "backtester run_one L1015-1017 passes h1_trend=ind['st'][i] (M30 Supertrend, same-TF) + hour; run_adaptive L1208-1209 same. Bot uses H1 ST, backtester uses M30 ST — minor semantic gap in the ST-alignment gate (both are 'context trend').",
        "harness evaluate() -> run_one uses same-TF ST. Live bot's H1-ST filter is slightly stricter/looser depending on TF divergence but not a bug.",
        "bot get_signal L643 fn(I,i) no hour — returns None for non-H1 tf, S10 is M30 so never hit.",
    ],
    'combos_tested': combos10,
    'winner': best10[0] if best10 else None,
}

# ═══════════════════════════ S09_MFKK_SCALPING (M30, hard-blocked) ══════════
print("\n" + "#"*90 + "\n# S09_MFKK_SCALPING (hard-blocked)\n" + "#"*90)
NAME = 'S09_MFKK_SCALPING'
base09 = evaluate(NAME, signal_mfkk_scalping, tf='M30', tp_mult=4.0, sl_mult=1.5)
print_eval("S09 BASELINE M30 4.0/1.5", base09)
combos09 = []
best09 = None
UNBLOCK_MIN_PF = 1.15
UNBLOCK_MIN_N = 30
sessions9 = {'6-19': (6,19), '7-17': (7,17), '9-15': (9,15)}
for adx in (15, 20, 25):
    for sk, sv in sessions9.items():
        for rsi_c in (True, False):
            for obv_c in (True, False):
                for (tpm, slm) in [(3.5,1.5),(4.0,1.5),(4.5,1.5),(4.0,1.25),(4.5,1.25)]:
                    fn = make_s09(adx_gate=adx, session=sv, rsi_conf=rsi_c, obv_conf=obv_c)
                    ev = evaluate(NAME, fn, tf='M30', tp_mult=tpm, sl_mult=slm)
                    h = ev['holdout']
                    unblockable = (h['pf'] >= UNBLOCK_MIN_PF and h['n'] >= UNBLOCK_MIN_N
                                   and ev['full']['pf'] >= 1.10 and pos_folds(ev) >= 2)
                    rec = {'adx_gate': adx, 'session': sk, 'rsi_conf': rsi_c, 'obv_conf': obv_c,
                           'tp_mult': tpm, 'sl_mult': slm,
                           'holdout_pf': h['pf'], 'holdout_pnl': h['pnl'], 'holdout_n': h['n'],
                           'full_pf': ev['full']['pf'], 'full_pnl': ev['full']['pnl'],
                           'n_trades': ev['n_trades'], 'pos_folds': pos_folds(ev),
                           'unblockable': unblockable}
                    combos09.append(rec)
                    if unblockable and (best09 is None or h['pf'] > best09[1]['holdout']['pf']):
                        best09 = (rec, ev)
RESULT['S09_MFKK_SCALPING'] = {
    'primary_tf': 'M30',
    'hard_blocked': True,
    'baseline_ev': summ(base09),
    'callpath_mismatches': [
        "signal_mfkk_scalping: bot M30 block L2424 passes h1_trend=curr_h1_trend (H1 ST) + hour — CORRECT since 2026-07-17.",
        "backtester run_one L1015-1017 / run_adaptive L1208-1209 pass h1_trend=ind['st'][i] (same-TF ST) + hour.",
        "Pre-2026-07-17 bug (hour landing in h1_trend positionally) already fixed; not re-introduced.",
        "S09 is hard-blocked in data/strategy_overrides.json (score_mult 0.0) AND absent from live routing effect via quality_gate is_hard_blocked() L652.",
    ],
    'combos_tested': combos09,
    'winner': best09[0] if best09 else None,
    'unblock_criteria': f"holdout PF >= {UNBLOCK_MIN_PF} AND holdout n >= {UNBLOCK_MIN_N} AND full PF >= 1.10 AND pos_folds >= 2",
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(RESULT, f, indent=2, default=str)
print(f"\n\nSALVATO: {OUT}")

# console summary
for s, r in RESULT.items():
    w = r.get('winner')
    print(f"\n{s}: baseline holdout PF={r['baseline_ev']['holdout']['pf']} "
          f"n={r['baseline_ev']['holdout']['n']} | winner={'NONE' if not w else w}")
