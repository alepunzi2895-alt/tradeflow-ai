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
    is_promotable(ev_new, ev_base, num_trials=None) → True SOLO se
      - ev_new['holdout']['pf'] > ev_base['holdout']['pf']  (batte il baseline sull'holdout)
      - ev_new['holdout']['pnl'] > ev_base['holdout']['pnl']
      - fold positivi (pf>=1.0) di ev_new >= max(2, fold positivi base)
      - ev_new['holdout']['dd'] <= 1.35 * max(ev_base['holdout']['dd'], 1.0)
      - 0.3 <= trade/giorno <= 15  (full period)
      - [SOLO SE num_trials è passato] Deflated Sharpe Ratio sull'holdout > 0.95
        (vedi dsr_check — corregge lo Sharpe per multiple-testing: num_trials =
        quante varianti/parametri sono state provate in questa sprint PRIMA di
        arrivare a questa configurazione. Va dichiarato onestamente dall'owner,
        non c'è modo di dedurlo automaticamente. Se num_trials non è passato il
        check DSR è saltato — comportamento invariato per compatibilità.)

Il backtester è caricato via importlib (filename con trattino). Gli indicatori sono
calcolati una volta per TF e messi in cache.

DSR/PBO (overfit_detector.py) vengono dalla skill walk-forward-validation
(.claude/skills/walk-forward-validation/scripts/overfit_detector.py) — richiede
`pip install scipy` (già installato).
"""
import sys, os, io, importlib.util, functools
import numpy as np

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

_OVERFIT = None


def _load_overfit_detector():
    """Carica overfit_detector.py dalla skill walk-forward-validation (DSR/PBO)."""
    global _OVERFIT
    if _OVERFIT is None:
        path = os.path.join(HERE, "..", ".claude", "skills", "walk-forward-validation",
                             "scripts", "overfit_detector.py")
        spec = importlib.util.spec_from_file_location("overfit_detector", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["overfit_detector"] = mod  # richiesto da dataclasses per risolvere cls.__module__
        spec.loader.exec_module(mod)
        _OVERFIT = mod
    return _OVERFIT


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


def daily_pnl_series(trades):
    """Serie di P&L giornaliero (somma trade per giorno), ordinata per data. numpy array."""
    by_day = {}
    for t in trades:
        by_day[t['date']] = by_day.get(t['date'], 0.0) + t['pnl']
    days = sorted(by_day)
    return np.array([by_day[d] for d in days], dtype=float)


def sharpe_from_pnl(daily_pnl, periods_per_year=252):
    """Sharpe annualizzato dalla serie di P&L giornaliero. Non normalizzato per equity —
    valido come confronto relativo tra varianti sullo stesso conto/istante/periodo."""
    if len(daily_pnl) < 2 or daily_pnl.std() == 0:
        return 0.0
    return float(daily_pnl.mean() / daily_pnl.std() * np.sqrt(periods_per_year))


def dsr_check(ev, num_trials, holdout_frac=0.2, min_days=10):
    """Deflated Sharpe Ratio sull'holdout di `ev` (da evaluate()).

    num_trials = quante varianti/combinazioni di parametri sono state provate in
    questa sprint PRIMA di arrivare a questa configurazione — va dichiarato
    onestamente da chi chiama (nessun modo di dedurlo dai dati). Un num_trials
    sottostimato gonfia artificialmente il DSR.

    Ritorna None se l'holdout ha meno di `min_days` giorni con trade (troppo
    pochi per una stima di Sharpe sensata) — in quel caso il check va considerato
    "non disponibile", non "passato".
    """
    from scipy.stats import skew as _skew, kurtosis as _kurt
    od = _load_overfit_detector()
    _, holdout_trades = SE2.split_holdout(ev.get('trades', []), holdout_frac)
    pnl = daily_pnl_series(holdout_trades)
    if len(pnl) < min_days:
        return None
    sr = sharpe_from_pnl(pnl)
    sk = float(_skew(pnl)) if pnl.std() else 0.0
    ku = float(_kurt(pnl, fisher=False)) if pnl.std() else 3.0
    return od.deflated_sharpe_ratio(
        observed_sr=sr, num_trials=num_trials, backtest_length=len(pnl),
        skewness=sk, kurtosis=ku, annualization=np.sqrt(252),
    )


def pbo_check(variants, n_groups=6, n_test_groups=2):
    """Probability of Backtest Overfitting su più varianti candidate.

    `variants`: dict {nome: trades} — tipicamente i risultati di più configurazioni
    provate nella stessa sprint (es. combinazioni tp_mult/sl_mult diverse). Le serie
    di P&L giornaliero vengono allineate sull'unione delle date (giorni senza trade
    per una variante = 0). Richiede almeno 2 varianti e n_groups*group_size giorni.
    """
    od = _load_overfit_detector()
    all_days = sorted(set(d for trades in variants.values() for d in (t['date'] for t in trades)))
    by_variant = {}
    for name, trades in variants.items():
        by_day = {}
        for t in trades:
            by_day[t['date']] = by_day.get(t['date'], 0.0) + t['pnl']
        by_variant[name] = [by_day.get(d, 0.0) for d in all_days]
    names = list(variants.keys())
    arr = np.array([by_variant[n] for n in names], dtype=float).T  # (n_obs, n_strategies)
    return od.probability_of_backtest_overfitting(arr, n_groups=n_groups, n_test_groups=n_test_groups)


def is_promotable(ev_new, ev_base, num_trials=None):
    h_new, h_base = ev_new['holdout'], ev_base['holdout']
    f = ev_new['full']
    checks = {
        'holdout_pf':  h_new['pf'] > h_base['pf'],
        'holdout_pnl': h_new['pnl'] > h_base['pnl'],
        'folds_pos':   pos_folds(ev_new) >= max(2, pos_folds(ev_base)),
        'dd_ok':       h_new['dd'] <= 1.35 * max(h_base['dd'], 1.0),
        'freq_ok':     0.3 <= f['tr_day'] <= 15,
    }
    if num_trials is not None:
        dsr = dsr_check(ev_new, num_trials)
        checks['dsr_ok'] = dsr.is_significant if dsr is not None else True
    return all(checks.values()), checks


def fmt(s):
    if not s or not s.get('n'):
        return 'n=0'
    return (f"n={s['n']:>4} WR={s['wr']:>5.1f}% PF={s['pf']:>6.3f} "
            f"pnl={s['pnl']:>9.1f} DD={s['dd']:>8.1f} mesi+={s['months']}")


def print_eval(label, ev, num_trials=None):
    print(f"\n=== {label} ===")
    print(f"  full   : {fmt(ev['full'])}")
    for k, s in enumerate(ev['folds'], 1):
        print(f"  fold {k} : {fmt(s)}")
    print(f"  HOLDOUT: {fmt(ev['holdout'])}   (da {ev['holdout_start']})")
    print(f"  live win {LIVE_WINDOW[0]}..{LIVE_WINDOW[1]}: {fmt(ev['live'])}")
    print(f"  fold positivi: {pos_folds(ev)}/{len(ev['folds'])}")
    if num_trials is not None:
        dsr = dsr_check(ev, num_trials)
        if dsr is None:
            print(f"  DSR: n/d (holdout troppo corto)")
        else:
            sig = 'SIGNIFICATIVO' if dsr.is_significant else 'non significativo'
            print(f"  DSR: sr={dsr.observed_sr:.3f} p-value={dsr.dsr_pvalue:.3f} "
                  f"({sig}, num_trials={num_trials})")


if __name__ == '__main__':
    # smoke test
    from signals import signal_mfkk_score, signal_golden_squeeze
    print_eval("S00_MFKK H1 baseline", evaluate('S00_MFKK', signal_mfkk_score, 'H1'), num_trials=1)
    print_eval("S16_GOLDEN_SQUEEZE H1 baseline", evaluate('S16_GOLDEN_SQUEEZE', signal_golden_squeeze, 'H1'), num_trials=1)
