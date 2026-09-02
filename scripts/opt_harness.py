#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Harness condiviso per la sprint di ottimizzazione parametri (2026-09-02)

Fornisce a tutti i subagenti della sprint UNA sola funzione di fitness, così che i
risultati siano confrontabili:

    ev = evaluate(name, signal_fn, tf='H1', tp_mult=3.5, sl_mult=1.5,
                  folds=4, holdout_frac=0.2)

`ev` = {
    'full':   stats sull'intero periodo (cost model ON, fill pessimistico, entry next-open),
    'folds':  [stats, ...]  (N blocchi cronologici di training),
    'holdout':stats           (ultimo holdout_frac dei giorni — MAI usato per scegliere),
    'holdout_start': 'YYYY-MM-DD',
    'live':   stats ristretti alla finestra dei trade reali (2026-04-14 → 2026-07-10),
    'trades': lista completa,
}

Regola di promozione (identica per tutti gli owner):
    is_promotable(ev_new, ev_base) → True SOLO se
      - ev_new['holdout']['pf'] > ev_base['holdout']['pf']  (batte il baseline sull'holdout)
      - ev_new['holdout']['pnl'] > ev_base['holdout']['pnl']
      - fold positivi (pf>=1.0) di ev_new >= max(2, fold positivi base)
      - ev_new['holdout']['dd'] <= 1.35 * max(ev_base['holdout']['dd'], 1.0)
      - 0.3 <= trade/giorno <= 15  (full period)

Il backtester è caricato via importlib (filename con trattino). Gli indicatori sono
calcolati una volta per TF e messi in cache.
"""
import sys, os, io, importlib.util, functools

HERE = os.path.dirname(os.path.abspath(__file__))
_REAL_STDOUT = sys.stdout

DATA = {
    'M5':  os.path.join(HERE, '..', 'data', 'xauusd_m5_mt5.json'),
    'M15': os.path.join(HERE, '..', 'data', 'xauusd_m15_mt5.json'),
    'M30': os.path.join(HERE, '..', 'data', 'xauusd_m30_mt5.json'),
    'H1':  os.path.join(HERE, '..', 'data', 'xauusd_h1_mt5.json'),
    'H4':  os.path.join(HERE, '..', 'data', 'xauusd_h4_mt5.json'),
}

LIVE_WINDOW = ('2026-04-14', '2026-07-10')   # finestra dei trade reali in performance_cache.json


def _load_engine(extra_argv=None):
    spec = importlib.util.spec_from_file_location("se2_harness", os.path.join(HERE, "strategy-engine-v2.py"))
    se2 = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = [saved[0]] + (extra_argv or [])
    try:
        spec.loader.exec_module(se2)
    finally:
        sys.argv = saved
        try:
            if sys.stdout is not _REAL_STDOUT:
                sys.stdout.detach()
        except Exception:
            pass
        sys.stdout = _REAL_STDOUT
    return se2


SE2 = _load_engine()          # cost model ON di default


@functools.lru_cache(maxsize=8)
def _data_for(tf):
    candles, tf_loaded = SE2.load_from_file(DATA[tf])
    ind = SE2.compute_all(candles)
    return candles, ind


def evaluate(name, signal_fn, tf='H1', tp_mult=None, sl_mult=None, folds=4, holdout_frac=0.2):
    """Backtest standalone realistico + walk-forward + holdout + finestra live.
    tp_mult/sl_mult: multipli di ATR; se None run_one usa la tabella hardcoded per `name`."""
    candles, ind = _data_for(tf)
    trades = SE2.run_one(candles, ind, name, signal_fn, tf=tf, tp_mult=tp_mult, sl_mult=sl_mult)
    wf = SE2.walk_forward_report(trades, folds=folds, holdout_frac=holdout_frac)
    lo, hi = LIVE_WINDOW
    live = SE2.stats([t for t in trades if lo <= t['date'] <= hi])
    return {
        'full': wf['full'] if wf else SE2.stats(trades),
        'folds': wf['folds'] if wf else [],
        'holdout': wf['holdout'] if wf else SE2.stats([]),
        'holdout_start': wf['holdout_start'] if wf else None,
        'live': live,
        'n_trades': len(trades),
        'trades': trades,
    }


def pos_folds(ev):
    return sum(1 for s in ev['folds'] if s['pf'] >= 1.0)


def is_promotable(ev_new, ev_base):
    h_new, h_base = ev_new['holdout'], ev_base['holdout']
    f = ev_new['full']
    checks = {
        'holdout_pf':  h_new['pf'] > h_base['pf'],
        'holdout_pnl': h_new['pnl'] > h_base['pnl'],
        'folds_pos':   pos_folds(ev_new) >= max(2, pos_folds(ev_base)),
        'dd_ok':       h_new['dd'] <= 1.35 * max(h_base['dd'], 1.0),
        'freq_ok':     0.3 <= f['tr_day'] <= 15,
    }
    return all(checks.values()), checks


def fmt(s):
    if not s or not s.get('n'):
        return 'n=0'
    return (f"n={s['n']:>4} WR={s['wr']:>5.1f}% PF={s['pf']:>6.3f} "
            f"pnl={s['pnl']:>9.1f} DD={s['dd']:>8.1f} mesi+={s['months']}")


def print_eval(label, ev):
    print(f"\n=== {label} ===")
    print(f"  full   : {fmt(ev['full'])}")
    for k, s in enumerate(ev['folds'], 1):
        print(f"  fold {k} : {fmt(s)}")
    print(f"  HOLDOUT: {fmt(ev['holdout'])}   (da {ev['holdout_start']})")
    print(f"  live win {LIVE_WINDOW[0]}..{LIVE_WINDOW[1]}: {fmt(ev['live'])}")
    print(f"  fold positivi: {pos_folds(ev)}/{len(ev['folds'])}")


if __name__ == '__main__':
    # smoke test
    from signals import signal_mfkk_score, signal_golden_squeeze
    print_eval("S00_MFKK H1 baseline", evaluate('S00_MFKK', signal_mfkk_score, 'H1'))
    print_eval("S16_GOLDEN_SQUEEZE H1 baseline", evaluate('S16_GOLDEN_SQUEEZE', signal_golden_squeeze, 'H1'))
