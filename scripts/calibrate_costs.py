#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Calibrazione cost model del backtester (2026-09-02)

Confronta il PF/WR che `strategy-engine-v2.py` (cost model ON) produce per S00_MFKK e
S16_GOLDEN_SQUEEZE sulla STESSA finestra dei trade reali (`data/performance_cache.json`)
e fa un mini-sweep di HALF_SPREAD_USD / SLIP_SL_USD scegliendo i valori che minimizzano
|PF_bt - PF_live| aggregato su S00+S16.

NB: lo storico reale è dominato da una sotto-finestra sfavorevole (apr-lug 2026, la stessa
in cui il walk-forward mostra l'edge decaduto a ~breakeven). L'obiettivo NON è forzare un
match perfetto — è verificare che il backtester realistico sia nel ballpark del live, non
0.5 PF sopra come prima. Vedi directives/05_backtest.md.

Uso: python scripts/calibrate_costs.py
"""
import sys, os, io, json, importlib.util, datetime, collections

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

# strategy-engine-v2.py rimpiazza sys.stdout con un TextIOWrapper sul buffer grezzo a
# ogni import; ri-eseguirlo più volte fa chiudere il buffer sottostante al GC del vecchio
# wrapper. Teniamo un riferimento stabile e lo ripristiniamo dopo ogni exec_module.
_REAL_STDOUT = sys.stdout

LIVE_CACHE = os.path.join(HERE, '..', 'data', 'performance_cache.json')
H1_FILE    = os.path.join(HERE, '..', 'data', 'xauusd_h1_mt5.json')

# ── PF/WR reali per strategia dalla cache ────────────────────────────────────
def live_stats():
    d = json.load(open(LIVE_CACHE, encoding='utf-8'))
    by = collections.defaultdict(list)
    for t in d['trades']:
        by[t['strategy_id']].append(t)
    out = {}
    lo, hi = '9999', '0000'
    for sid, ts in by.items():
        wins = [t for t in ts if t['profit'] > 0]
        loss = [t for t in ts if t['profit'] <= 0]
        gp = sum(t['profit'] for t in wins)
        gl = abs(sum(t['profit'] for t in loss)) or 1e-9
        out[sid] = {'n': len(ts), 'wr': round(100*len(wins)/len(ts), 1),
                    'pf': round(gp/gl, 3), 'pnl': round(sum(t['profit'] for t in ts), 2)}
        for t in ts:
            lo = min(lo, t['time_close'][:10]); hi = max(hi, t['time_close'][:10])
    out['_window'] = (lo, hi)
    return out


def load_engine(half_spread, slip_sl):
    """(ri)carica strategy-engine-v2.py con override dei parametri di costo via argv."""
    for m in list(sys.modules):
        if m in ('se2_cal',):
            del sys.modules[m]
    spec = importlib.util.spec_from_file_location("se2_cal", os.path.join(HERE, "strategy-engine-v2.py"))
    se2 = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = [saved[0], '--spread', str(half_spread), '--sl-slippage', str(slip_sl)]
    try:
        spec.loader.exec_module(se2)
    finally:
        sys.argv = saved
        try:
            if sys.stdout is not _REAL_STDOUT:
                sys.stdout.detach()   # sgancia il buffer prima che il wrapper venga GC'd
        except Exception:
            pass
        sys.stdout = _REAL_STDOUT
    return se2


def bt_stats_in_window(se2, candles, ind, name, fn, tf, lo, hi):
    trades = se2.run_one(candles, ind, name, fn, tf=tf)
    w = [t for t in trades if lo <= t['date'] <= hi]
    return se2.stats(w)


def main():
    live = live_stats()
    lo, hi = live['_window']
    print(f"Finestra live: {lo} → {hi}")
    print(f"Live  S00_MFKK           : {live.get('S00_MFKK')}")
    print(f"Live  S16_GOLDEN_SQUEEZE : {live.get('S16_GOLDEN_SQUEEZE')}")
    print()

    se2_boot = load_engine(0.15, 0.10)
    candles, tf = se2_boot.load_from_file(H1_FILE)
    ind = se2_boot.compute_all(candles)
    print(f"Dati H1: {len(candles)} candele (TF={tf})\n")

    targets = {
        'S00_MFKK':           (se2_boot.se_signal_mfkk_score, live['S00_MFKK']['pf']),
        'S16_GOLDEN_SQUEEZE': (se2_boot.s_golden_squeeze,     live['S16_GOLDEN_SQUEEZE']['pf']),
    }

    grid_spread = [0.15, 0.25, 0.35, 0.45]
    grid_slipsl = [0.10, 0.20, 0.30]
    print(f"{'spread':>7} {'slipSL':>7} | {'S00 PF':>7} {'S00 WR':>7} {'S00 n':>6} | "
          f"{'S16 PF':>7} {'S16 WR':>7} {'S16 n':>6} | {'err':>7}")
    best = None
    for hs in grid_spread:
        for ss in grid_slipsl:
            se2 = load_engine(hs, ss)
            ind_l = se2.compute_all(candles) if se2 is not se2_boot else ind
            row = {}
            err = 0.0
            for name, (fn, pf_live) in targets.items():
                s = bt_stats_in_window(se2, candles, ind_l, name, fn, tf, lo, hi)
                row[name] = s
                err += abs(s['pf'] - pf_live)
            s0, s16 = row['S00_MFKK'], row['S16_GOLDEN_SQUEEZE']
            print(f"{hs:>7.2f} {ss:>7.2f} | {s0['pf']:>7.3f} {s0['wr']:>7.1f} {s0['n']:>6} | "
                  f"{s16['pf']:>7.3f} {s16['wr']:>7.1f} {s16['n']:>6} | {err:>7.3f}")
            if best is None or err < best['err']:
                best = {'spread': hs, 'slip_sl': ss, 'err': err, 's0': s0, 's16': s16}

    print()
    print(f"→ Migliore: HALF_SPREAD_USD={best['spread']}  SLIP_SL_USD={best['slip_sl']}  (err aggregato {best['err']:.3f})")
    print(f"  S00 bt PF {best['s0']['pf']} vs live {targets['S00_MFKK'][1]}")
    print(f"  S16 bt PF {best['s16']['pf']} vs live {targets['S16_GOLDEN_SQUEEZE'][1]}")
    out = {
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'live_window': [lo, hi],
        'live': {k: v for k, v in live.items() if k != '_window'},
        'best': {'half_spread_usd': best['spread'], 'slip_sl_usd': best['slip_sl'],
                 'err': round(best['err'], 3),
                 's00_bt': best['s0'], 's16_bt': best['s16']},
    }
    p = os.path.join(HERE, '..', 'backtests', 'results', 'calibrate_costs_2026-09-02.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), indent=2, default=str)
    print(f"\nSalvato: {p}")


if __name__ == '__main__':
    main()
