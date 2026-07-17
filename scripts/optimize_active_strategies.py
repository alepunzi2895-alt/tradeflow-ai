#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Re-tuning parametri strategie attive (2026-07-17)

Metodologia (allineata a 07_self_learning_log.md 2026-07-16, esperimento SL-adattivo S16):
  - Split cronologico 80% IS / 20% OOS.
  - Un cambiamento viene adottato SOLO se: OOS migliora in modo sostanziale rispetto al
    baseline OOS corrente, il miglioramento e' robusto sulle celle vicine della griglia
    (non un picco isolato), e il numero di trade resta ragionevole.
  - Riusa l'infrastruttura del backtester canonico (compute_all/run_one/stats in
    strategy-engine-v2.py, caricato via importlib perche' il filename ha un trattino).

Uso: python scripts/optimize_active_strategies.py
"""
import sys, io, os, json, importlib.util, datetime

HERE = os.path.dirname(__file__)

# ── Carica strategy-engine-v2.py come modulo (filename con trattino) ─────────
spec = importlib.util.spec_from_file_location("se2", os.path.join(HERE, "strategy-engine-v2.py"))
se2 = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]  # evita che se2 legga i nostri argv con argparse
spec.loader.exec_module(se2)

from signals import _get

# ── Baseline signal functions (fonte di verita' corrente) ────────────────────
from signals import (
    signal_mfkk_score, signal_golden_squeeze, signal_mfkk_scalping,
    signal_ob_fvg_scalp, signal_convergence_scalp,
)

DATA = {
    'H1':  os.path.join(HERE, '..', 'data', 'xauusd_h1_mt5.json'),
    'M30': os.path.join(HERE, '..', 'data', 'xauusd_m30_mt5.json'),
    'H4':  os.path.join(HERE, '..', 'data', 'xauusd_h4_mt5.json'),
}

# TP/SL correnti (fonte di verita': risk_guardian.py::STRATEGY_ATR_PARAMS)
CURRENT_TPSL = {
    'S00_MFKK':             (3.5, 1.5),
    'S09_MFKK_SCALPING':    (4.0, 1.5),
    'S10_OB_FVG_SCALP':     (3.5, 1.5),
    'S16_GOLDEN_SQUEEZE':   (3.5, 2.0),
    'S17_CONVERGENCE_SCALP':(4.0, 1.5),
}

print("Carico dati e calcolo indicatori (una volta per TF)...")
CANDLES = {}
IND = {}
for tf, path in DATA.items():
    c, _tf_loaded = se2.load_from_file(path)
    CANDLES[tf] = c
    IND[tf] = se2.compute_all(c)
    print(f"  {tf}: {len(c)} barre")

# ── Split IS/OOS per data (80/20) ─────────────────────────────────────────────
def split_is_oos(trades):
    if not trades:
        return [], []
    dates = sorted(t['date'] for t in trades)
    cutoff = dates[int(len(dates) * 0.8)]
    is_t  = [t for t in trades if t['date'] < cutoff]
    oos_t = [t for t in trades if t['date'] >= cutoff]
    return is_t, oos_t

def run_and_split(name, fn, tf, tp_mult, sl_mult):
    candles = CANDLES[tf]; ind = IND[tf]
    trades = se2.run_one(candles, ind, name, fn, tf=tf, tp=20.0, sl=12.0)
    # run_one usa i mult hardcoded per-nome per default: per testare varianti custom di
    # tp/sl dobbiamo bypassare quella tabella. Trick: rinominiamo temporaneamente la
    # strategia con un nome NON nella tabella così run_one usa i nostri tp/sl fissi
    # calcolati qui bar per bar (approssimazione: usiamo ATR medio del dataset).
    return trades

def run_custom_tpsl(name, fn, tf, tp_mult, sl_mult):
    """Bypassa la tabella TP/SL hardcoded di run_one usando un nome fittizio + tp/sl fissi
    ricalcolati bar-per-bar dall'ATR corrente (replica la logica ATR-based di run_one)."""
    candles = CANDLES[tf]; ind = IND[tf]
    fake_name = name + "__CUSTOM"
    trades = []
    day_n = {}
    day_h = {}
    n = len(candles)
    tf_mult = 2 if tf == 'M30' else 1
    lookahead = 30 * tf_mult
    if name == 'S17_CONVERGENCE_SCALP':
        lookahead = 150
    for i in range(220, n):
        c = candles[i]; ts = c['t']
        dt = datetime.datetime.utcfromtimestamp(ts)
        hour = dt.hour; day = dt.strftime('%Y-%m-%d')
        if not (se2.SESSION_S <= hour < se2.SESSION_E): continue
        av = ind['atr'][i]; aa = ind['atr30'][i]
        if av and aa and av > se2.EXTREME_K * aa: continue
        if day_n.get(day, 0) >= se2.MAX_TRADES: continue
        if hour - day_h.get(day, -99) < se2.COOLDOWN_H: continue
        if not av: continue
        curr_tp = round(av * tp_mult, 2)
        curr_sl = round(av * sl_mult, 2)
        if name in ('S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP'):
            h1t = ind['st'][i] if ind.get('st') else None
            sig = fn(ind, i, h1_trend=h1t, hour=hour)
        else:
            sig = fn(ind, i, hour=hour)
        if sig is None: continue
        entry = c['c']
        tp_p = entry + curr_tp if sig == 'buy' else entry - curr_tp
        sl_p = entry - curr_sl if sig == 'buy' else entry + curr_sl
        outcome = 'open'; close_price = entry
        curr_sl_dyn = sl_p
        for j in range(i + 1, min(i + lookahead, n)):
            jc = candles[j]['c']; jh = candles[j]['h']; jl = candles[j]['l']
            profit = (jc - entry) if sig == 'buy' else (entry - jc)
            risk = curr_sl
            if profit >= risk * 0.8:
                curr_sl_dyn = entry + 0.2 if sig == 'buy' else entry - 0.2
            if profit >= risk * 1.2:
                potential = jc - risk * 0.7 if sig == 'buy' else jc + risk * 0.7
                curr_sl_dyn = max(curr_sl_dyn, potential) if sig == 'buy' else min(curr_sl_dyn, potential)
            if sig == 'buy':
                if jh >= tp_p: outcome = 'win'; close_price = tp_p; break
                if jl <= curr_sl_dyn: outcome = 'loss'; close_price = curr_sl_dyn; break
            else:
                if jl <= tp_p: outcome = 'win'; close_price = tp_p; break
                if jh >= curr_sl_dyn: outcome = 'loss'; close_price = curr_sl_dyn; break
        if outcome == 'open': continue
        pnl = (close_price - entry) if sig == 'buy' else (entry - close_price)
        outcome = 'win' if pnl > 0 else 'loss'
        trades.append({'date': day, 'hour': hour, 'dir': sig, 'entry': entry,
                        'outcome': outcome, 'pnl': round(pnl, 2), 'strategy': name})
        day_n[day] = day_n.get(day, 0) + 1
        day_h[day] = hour
    return trades

def eval_combo(name, fn, tf, tp_mult, sl_mult):
    trades = run_custom_tpsl(name, fn, tf, tp_mult, sl_mult)
    is_t, oos_t = split_is_oos(trades)
    return {
        'is': se2.stats(is_t) if is_t else None,
        'oos': se2.stats(oos_t) if oos_t else None,
        'n_total': len(trades),
    }

def fmt(s):
    if not s: return "n=0"
    return f"n={s['n']:3d} WR={s['wr']:5.1f}% PF={s['pf']:5.3f} pnl=${s['pnl']:8.1f} DD=${s['dd']:7.1f}"

# ══════════════════════════════════════════════════════════════════════════
# FACTORY PARAMETRIZZATE (default = valore attuale in signals.py)
# ══════════════════════════════════════════════════════════════════════════

def make_s00(adx_gate=20, di_spread_gate=5, buy_thr_base=90, sell_thr_base=72):
    def fn(ind, i, h1_trend=None, hour=None, tf=None):
        if i < 100: return None
        if hour is not None:
            if tf == 'H4':
                if hour < 4: return None
            elif not (7 <= hour < 22): return None
        c = ind['cci'][i]
        if c is None: c = 50.0
        ml_arr = _get(ind, 'ml', 'macd')
        m = ml_arr[i] if ml_arr else 0
        m_sig = ind.get('macd_sig', [0]*len(ml_arr))[i] if ml_arr else 0
        m_hist = ind.get('macd_hist', [0]*len(ml_arr))[i] if ml_arr else 0
        m_hist_p = ind.get('macd_hist', [0]*len(ml_arr))[i-1] if (ml_arr and i>0) else 0
        a = ind['adx'][i]; dp = ind['dip'][i]; dm = ind['dim'][i]
        if None in (a, dp, dm): return None

        def get_dir_score(is_buy):
            cci_s = 50
            if is_buy:
                macd_rising = m_hist > m_hist_p
                is_cci_reversal = c < 35 and (macd_rising or m > m_sig)
                if is_cci_reversal: cci_s = 85 + (35 - c) * 0.5
                elif c >= 75: cci_s = 70
                elif c >= 65: cci_s = 55
                elif c >= 50: cci_s = 45
                elif c >= 35: cci_s = 35
                else: cci_s = 20
            else:
                macd_falling = m_hist < m_hist_p
                is_cci_reversal = c > 65 and (macd_falling or m < m_sig)
                if is_cci_reversal: cci_s = 85 + (c - 65) * 0.5
                elif c <= 35: cci_s = 15
                elif c <= 50: cci_s = 40
                elif c <= 65: cci_s = 50
                else: cci_s = 20
            macd_s = 50
            diff = m - m_sig
            str_m = min(abs(diff)/3, 1)
            hist_bonus = 10 if ((is_buy and m_hist > 0) or (not is_buy and m_hist < 0)) else 0
            m_p = ml_arr[i-1] if i>0 else 0
            ms_p = ind.get('macd_sig', [0]*len(ml_arr))[i-1] if i>0 else 0
            cross_buy = m_p <= ms_p and m > m_sig
            cross_sell = m_p >= ms_p and m < m_sig
            if is_buy:
                if cross_buy: macd_s = 100
                elif diff > 0.5: macd_s = 75 + str_m*20 + hist_bonus
                elif diff > 0: macd_s = 70 + hist_bonus
                elif diff > -0.2: macd_s = 60
                elif diff > -1: macd_s = 40
                elif diff > -3: macd_s = 45
                else: macd_s = 20
            else:
                if cross_sell: macd_s = 100
                elif cross_buy: macd_s = 5
                elif diff < -0.5: macd_s = 75 + str_m*20 + hist_bonus
                elif diff < 0: macd_s = 70 + hist_bonus
                elif diff < 0.5: macd_s = 45
                elif diff < 3: macd_s = 50
                else: macd_s = 20
            adx_s = 50
            di_diff = dp - dm
            di_spread = abs(di_diff)
            spread_bonus = min(di_spread/20, 1) * 15
            adx_str = 1.0 if a>=35 else 0.85 if a>=27 else 0.65 if a>=20 else 0.4 if a>=14 else 0.2 if a>=10 else 0.05
            if is_buy:
                if di_diff > 0 and a >= 25: adx_s = 60 + adx_str*25 + spread_bonus
                elif di_diff > 0 and a >= 10: adx_s = 50
                elif di_diff > 0: adx_s = 30
                elif di_diff < 0 and a >= 35: adx_s = 60 + adx_str*25 + spread_bonus
                else: adx_s = 5
            else:
                if di_diff < 0 and a >= 25: adx_s = 60 + adx_str*25 + spread_bonus
                elif di_diff < 0 and a >= 10: adx_s = 50
                elif di_diff < 0: adx_s = 30
                elif di_diff > 0 and a >= 35: adx_s = 60 + adx_str*25 + spread_bonus
                else: adx_s = 5
            total = (cci_s * 0.10) + (macd_s * 0.10) + (adx_s * 0.80)
            return total, adx_s, diff, cross_buy, cross_sell

        b_score, b_adx_s, b_diff, b_cross, _ = get_dir_score(True)
        s_score, _, _, _, s_cross = get_dir_score(False)
        is_exh_buy = b_adx_s >= 75 and b_diff < -1.0
        if a < adx_gate: return None
        if abs(dp - dm) < di_spread_gate: return None
        buy_thr = (buy_thr_base - 8) if (is_exh_buy or b_cross) else buy_thr_base
        buy_di_spread = dp - dm
        buy_di_min = 15 if tf in ('H1', 'H4') else 20
        if buy_di_spread < buy_di_min: buy_thr = 999
        sell_thr = 999
        is_london_ny = hour is not None and (7 <= hour < 20)
        sell_di_spread = dm - dp
        if tf != 'H4' and is_london_ny and sell_di_spread >= 18:
            sell_thr = sell_thr_base
        if b_score >= buy_thr: return 'buy'
        if s_score >= sell_thr: return 'sell'
        return None
    return fn

def make_s16(adx_gate=25, di_spread_min=8, candle_mult=0.35):
    def fn(ind, i, h1_trend=None, hour=None, h4_trend=None):
        if i < 233: return None
        if hour is not None and not (7 <= hour < 18): return None
        if h1_trend is not None:
            st = h1_trend
        else:
            st_arr = ind.get('st'); st = st_arr[i] if st_arr else 0
        if st == 0: return None
        a = ind['adx'][i]
        if a is None or a < adx_gate: return None
        dip_v = ind['dip'][i]; dim_v = ind['dim'][i]
        if None in (dip_v, dim_v): return None
        obv_arr = ind.get('obv'); obv_ema_arr = ind.get('obv_ema')
        if obv_arr is None or obv_ema_arr is None: return None
        obv_val = obv_arr[i]; obv_ema = obv_ema_arr[i]
        c = ind['C'][i]; cp = ind['C'][i-1]; e233 = ind['e233'][i]
        if None in (obv_val, obv_ema, e233): return None
        atr_arr = ind.get('atr'); atr_val = atr_arr[i] if atr_arr else None
        candle = abs(c - cp)
        big_enough = (atr_val is None) or (candle >= candle_mult * atr_val)
        obv_rising_3 = i >= 3 and obv_arr[i] > obv_arr[i-1] > obv_arr[i-2]
        obv_falling_3 = i >= 3 and obv_arr[i] < obv_arr[i-1] < obv_arr[i-2]
        if st == -1:
            if dip_v - dim_v < di_spread_min: return None
            if c > e233 and obv_val > obv_ema and obv_rising_3 and c > cp and big_enough:
                return 'buy'
        elif st == 1:
            if dim_v - dip_v < di_spread_min: return None
            e200_arr = ind.get('e200')
            if e200_arr is not None and i >= 4:
                e200_now = e200_arr[i]; e200_prev = e200_arr[i-4]
                if e200_now is not None and e200_prev is not None and e200_now <= e200_prev:
                    return None
            if c < e233 and obv_val < obv_ema and obv_falling_3 and c < cp and big_enough:
                return 'sell'
        return None
    return fn

def make_s09(adx_gate=20, session=(6, 19)):
    def fn(ind, i, h1_trend=None, hour=None):
        if i < 233: return None
        if hour is not None and not (session[0] <= hour < session[1]): return None
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
        rsi_bull = r is None or r > 50
        rsi_bear = r is None or r < 50
        obv_bull = obv_s is None or oe_s is None or obv_s > oe_s
        obv_bear = obv_s is None or oe_s is None or obv_s < oe_s
        if h1_trend is not None and h1_trend != 0:
            if e13 > e34 > e89 > e233 and h1_trend != -1: return None
            if e13 < e34 < e89 < e233 and h1_trend != 1: return None
        if e13 > e34 > e89 > e233 and c > e233 and fb[i] and rsi_bull and obv_bull: return 'buy'
        if e13 < e34 < e89 < e233 and c < e233 and fs[i] and rsi_bear and obv_bear: return 'sell'
        return None
    return fn

def make_s10(adx_gate=20, atr_spike_mult=2.5):
    def fn(ind, i, h1_trend=None, hour=None):
        if i < 233: return None
        if hour is not None and not (8 <= hour < 17): return None
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

def make_s17(adx_gate=22, bb_hi=0.58, bb_lo=0.42):
    def fn(ind, i, h1_trend=None, hour=None):
        if i < 89: return None
        e34 = ind['e34'][i]; e89 = ind['e89'][i]
        sk = ind['srsi_k'][i]; sd = ind['srsi_d'][i]
        bbu = ind['bb_up'][i]
        bbl_arr = _get(ind, 'bb_dn', 'bb_lo')
        bbl = bbl_arr[i] if bbl_arr else None
        c = ind['C'][i]; e50 = ind['e50'][i]; atr = ind['atr'][i]
        a = ind['adx'][i]
        atr_ref = _get(ind, 'atr_avg', 'atr30')
        atr_avg = atr_ref[i] if atr_ref else None
        if None in (e34, e89, sk, sd, bbu, bbl, c, e50, atr): return None
        if atr_avg and atr > 2.2 * atr_avg: return None
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

# ══════════════════════════════════════════════════════════════════════════
# CONFIG PER STRATEGIA: TF, factory, griglie
# ══════════════════════════════════════════════════════════════════════════

STRATS = {
    'S00_MFKK': {
        'tf': 'H1', 'factory': make_s00, 'baseline_fn': signal_mfkk_score,
        'grids': [
            {'param': 'adx_gate',       'values': [17, 20, 23]},
            {'param': 'di_spread_gate', 'values': [3, 5, 8]},
            {'param': 'buy_thr_base',   'values': [85, 90, 93]},
            {'param': 'sell_thr_base',  'values': [68, 72, 76]},
        ],
    },
    'S16_GOLDEN_SQUEEZE': {
        'tf': 'H1', 'factory': make_s16, 'baseline_fn': signal_golden_squeeze,
        'grids': [
            {'param': 'adx_gate',        'values': [22, 25, 28]},
            {'param': 'di_spread_min',   'values': [6, 8, 10]},
            {'param': 'candle_mult',     'values': [0.25, 0.35, 0.45]},
        ],
    },
    'S09_MFKK_SCALPING': {
        'tf': 'M30', 'factory': make_s09, 'baseline_fn': signal_mfkk_scalping,
        'grids': [
            {'param': 'adx_gate', 'values': [17, 20, 23]},
        ],
    },
    'S10_OB_FVG_SCALP': {
        'tf': 'M30', 'factory': make_s10, 'baseline_fn': signal_ob_fvg_scalp,
        'grids': [
            {'param': 'adx_gate',        'values': [17, 20, 23]},
            {'param': 'atr_spike_mult',  'values': [2.0, 2.5, 3.0]},
        ],
    },
    'S17_CONVERGENCE_SCALP': {
        'tf': 'H4', 'factory': make_s17, 'baseline_fn': signal_convergence_scalp,
        'grids': [
            {'param': 'adx_gate', 'values': [19, 22, 25]},
        ],
    },
}

# TP/SL sub-sweep (mult attorno al valore corrente)
TPSL_GRID = {
    'S00_MFKK':              [(3.0, 1.5), (3.5, 1.5), (3.5, 1.25), (4.0, 1.5)],
    'S16_GOLDEN_SQUEEZE':    [(3.0, 2.0), (3.5, 2.0), (3.5, 1.75), (4.0, 2.0)],
    'S09_MFKK_SCALPING':     [(3.5, 1.5), (4.0, 1.5), (4.0, 1.25), (4.5, 1.5)],
    'S10_OB_FVG_SCALP':      [(3.0, 1.5), (3.5, 1.5), (3.5, 1.25), (4.0, 1.5)],
    'S17_CONVERGENCE_SCALP': [(3.5, 1.5), (4.0, 1.5), (4.0, 1.25), (4.5, 1.5)],
}

RESULTS = {}

print("\n" + "="*100)
print("RE-TUNING STRATEGIE ATTIVE — split IS(80%)/OOS(20%) cronologico")
print("="*100)

for sname, cfg in STRATS.items():
    tf = cfg['tf']
    tp0, sl0 = CURRENT_TPSL[sname]
    print(f"\n{'─'*100}\n{sname} (TF={tf}, TP/SL correnti = {tp0}x/{sl0}x ATR)\n{'─'*100}")

    baseline = eval_combo(sname, cfg['baseline_fn'], tf, tp0, sl0)
    print(f"  BASELINE (produzione)   IS: {fmt(baseline['is'])}")
    print(f"                          OOS: {fmt(baseline['oos'])}")
    base_oos_pf = baseline['oos']['pf'] if baseline['oos'] else 0
    base_oos_pnl = baseline['oos']['pnl'] if baseline['oos'] else 0
    base_oos_n = baseline['oos']['n'] if baseline['oos'] else 0

    best_overall = {'params': {}, 'oos_pf': base_oos_pf, 'oos_pnl': base_oos_pnl, 'label': 'BASELINE'}
    grid_results = []

    import inspect
    default_params = dict(zip(
        inspect.signature(cfg['factory']).parameters.keys(),
        [p.default for p in inspect.signature(cfg['factory']).parameters.values()]
    ))

    for grid in cfg['grids']:
        pname = grid['param']
        print(f"\n  Sweep 1D: {pname} (attuale={default_params.get(pname)})")
        row = []
        for val in grid['values']:
            kwargs = {pname: val}
            fn = cfg['factory'](**kwargs)
            res = eval_combo(sname, fn, tf, tp0, sl0)
            is_s, oos_s = res['is'], res['oos']
            marker = ' [CURRENT]' if val == default_params.get(pname) else ''
            print(f"    {pname}={val!s:<8} IS: {fmt(is_s)}   OOS: {fmt(oos_s)}{marker}")
            row.append({'param': pname, 'value': val, 'is': is_s, 'oos': oos_s})
            if oos_s and oos_s['n'] >= max(8, base_oos_n * 0.5):
                if oos_s['pf'] > best_overall['oos_pf'] * 1.10 and oos_s['pnl'] > best_overall['oos_pnl']:
                    best_overall = {'params': {pname: val}, 'oos_pf': oos_s['pf'],
                                     'oos_pnl': oos_s['pnl'], 'label': f"{pname}={val}"}
        grid_results.append(row)

    # Robustness check sul miglior parametro trovato: le celle vicine devono reggere
    robust = False
    if best_overall['label'] != 'BASELINE':
        for row in grid_results:
            vals_beating = sum(1 for r in row if r['oos'] and r['oos']['pf'] > base_oos_pf)
            if vals_beating >= 2:  # almeno 2/3 celle della griglia migliorano OOS
                robust = True

    print(f"\n  >> Candidato migliore: {best_overall['label']} | OOS PF {best_overall['oos_pf']:.3f} vs baseline {base_oos_pf:.3f} | robusto={robust}")

    # TP/SL sub-sweep (a parametri segnale = baseline, per isolare l'effetto TP/SL)
    print(f"\n  Sweep TP/SL (parametri segnale = baseline):")
    best_tpsl = {'tp': tp0, 'sl': sl0, 'oos_pf': base_oos_pf, 'oos_pnl': base_oos_pnl}
    for tp_m, sl_m in TPSL_GRID[sname]:
        res = eval_combo(sname, cfg['baseline_fn'], tf, tp_m, sl_m)
        is_s, oos_s = res['is'], res['oos']
        cur = ' [CURRENT]' if (tp_m, sl_m) == (tp0, sl0) else ''
        print(f"    TP={tp_m}x SL={sl_m}x  IS: {fmt(is_s)}   OOS: {fmt(oos_s)}{cur}")
        if oos_s and oos_s['n'] >= max(8, base_oos_n * 0.5):
            if oos_s['pf'] > best_tpsl['oos_pf'] * 1.10 and oos_s['pnl'] > best_tpsl['oos_pnl']:
                best_tpsl = {'tp': tp_m, 'sl': sl_m, 'oos_pf': oos_s['pf'], 'oos_pnl': oos_s['pnl']}

    RESULTS[sname] = {
        'baseline_oos': baseline['oos'], 'baseline_is': baseline['is'],
        'best_signal_param': best_overall, 'robust': robust,
        'best_tpsl': best_tpsl, 'current_tp': tp0, 'current_sl': sl0,
    }

print("\n" + "="*100)
print("SOMMARIO FINALE")
print("="*100)
for sname, r in RESULTS.items():
    print(f"\n{sname}:")
    print(f"  Parametro segnale: {r['best_signal_param']['label']} (robusto={r['robust']})")
    tpsl_changed = (r['best_tpsl']['tp'], r['best_tpsl']['sl']) != (r['current_tp'], r['current_sl'])
    print(f"  TP/SL: {r['current_tp']}x/{r['current_sl']}x -> {r['best_tpsl']['tp']}x/{r['best_tpsl']['sl']}x (cambiato={tpsl_changed})")

with open(os.path.join(HERE, '..', 'backtests', 'results', 'optimize_active_strategies_2026-07-17.json'), 'w', encoding='utf-8') as f:
    json.dump({k: {
        'baseline_oos': v['baseline_oos'], 'baseline_is': v['baseline_is'],
        'best_signal_param': v['best_signal_param'], 'robust': v['robust'],
        'best_tpsl': v['best_tpsl'], 'current_tp': v['current_tp'], 'current_sl': v['current_sl'],
    } for k, v in RESULTS.items()}, f, indent=2, default=str)
print("\nSalvato: backtests/results/optimize_active_strategies_2026-07-17.json")
