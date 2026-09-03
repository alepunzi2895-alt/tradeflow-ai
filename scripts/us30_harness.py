#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Harness di ricerca strategie US30 (2026-09-03)
═══════════════════════════════════════════════════════════════════

Separato da opt_harness.py / strategy-engine-v2.py (che sono XAU-coupled: roster,
priority table, run_one con branch per-strategia). Qui:

  • dati: data/us30_{tf}_mt5.json  (fetch_mt5_history.py --asset us30 --all-tf)
  • cost model US30Cash: spread ~2 pt round-trip, slippage stop ~2.5 pt (gap-through
    su indici), entry ~0.5 pt, commissione 0. Override con --spread/--slippage/...
  • fill pessimistico (barra che tocca TP e SL = SL), entry al next-bar-open
  • walk-forward: N fold cronologici + holdout finale intoccabile (default 20%)

Le funzioni di segnale hanno firma:

    fn(candles, ind, i, dt) -> 'buy' | 'sell' | None

dove `dt` è un datetime UTC (aware) della candela chiusa `i`. Possono guardare
indietro liberamente in `candles`/`ind` (es. per costruire l'opening range di oggi).

USO:
  python scripts/us30_harness.py                          # smoke test: tutte le strategie, tutti i TF sensati
  python scripts/us30_harness.py --tf M15 --strategy orb  # una strategia / un TF
  python scripts/us30_harness.py --spread 1.5             # override half-spread (pt indice)
"""
import sys, os, io, argparse, importlib.util, functools, json, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
_REAL_STDOUT = sys.stdout

DATA = {tf: os.path.join(HERE, '..', 'data', f'us30_{tf.lower()}_mt5.json')
        for tf in ('M5', 'M15', 'M30', 'H1', 'H4', 'D1')}

# ── Cost model US30Cash (punti indice — stessa unità del prezzo) ──────────────
#   round-trip ≈ 2*HALF_SPREAD + SLIP_ENTRY (+ SLIP_SL se uscita a stop)
DEFAULT_COSTS = dict(spread=1.0, slippage=0.5, sl_slippage=2.5, commission=0.0)

_ap = argparse.ArgumentParser(description='US30 strategy research harness', add_help=True)
_ap.add_argument('--tf', type=str, default=None, help='Timeframe singolo (default: quello sensato per la strategia)')
_ap.add_argument('--strategy', type=str, default=None, help='Nome singola strategia (default: tutte)')
_ap.add_argument('--spread', type=float, default=DEFAULT_COSTS['spread'], help='half-spread pt indice (default 1.0)')
_ap.add_argument('--slippage', type=float, default=DEFAULT_COSTS['slippage'])
_ap.add_argument('--sl-slippage', type=float, default=DEFAULT_COSTS['sl_slippage'])
_ap.add_argument('--commission', type=float, default=DEFAULT_COSTS['commission'])
_ap.add_argument('--folds', type=int, default=4)
_ap.add_argument('--holdout-frac', type=float, default=0.2)
_ap.add_argument('--no-costs', action='store_true')
ARGS, _ = _ap.parse_known_args()


def _load_engine():
    """strategy-engine-v2.py via importlib (filename col trattino). Serve solo per
    compute_all + stats + walk_forward_report + resolve_intrabar. Il cost model
    dell'engine NON è usato: applichiamo il nostro qui sotto."""
    spec = importlib.util.spec_from_file_location("se2_us30", os.path.join(HERE, "strategy-engine-v2.py"))
    se2 = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = [saved[0]]
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

SE2 = _load_engine()


def _trade_cost(is_stop):
    if ARGS.no_costs:
        return 0.0
    c = 2 * ARGS.spread + ARGS.slippage + ARGS.commission
    if is_stop:
        c += ARGS.sl_slippage
    return c


@functools.lru_cache(maxsize=8)
def _data_for(tf):
    with open(DATA[tf], 'r', encoding='utf-8') as f:
        raw = json.load(f)
    candles = raw['candles']
    ind = SE2.compute_all(candles)
    dts = [datetime.datetime.fromtimestamp(c['t'], tz=datetime.timezone.utc) for c in candles]
    return candles, ind, dts


# ── Backtest loop generico ───────────────────────────────────────────────────
def run_signal(tf, signal_fn, *, tp_mult=2.5, sl_mult=1.5,
               session=(0, 24), max_trades_day=3, cooldown_bars=2,
               max_hold_bars=None, be_trail=True, warmup=260):
    """Simula la strategia su tutto il periodo. Ritorna lista trade
    ({date, hour, dir, entry, outcome, pnl, strategy})."""
    candles, ind, dts = _data_for(tf)
    n = len(candles)
    atr = ind['atr']
    if max_hold_bars is None:
        per_h = {'M5': 12, 'M15': 4, 'M30': 2, 'H1': 1, 'H4': 0.25}.get(tf, 1)
        max_hold_bars = int(48 * per_h) or 12    # ~2 giorni di barre

    trades = []
    day_n = defaultdict(int)
    last_entry_bar = -10 ** 9

    for i in range(warmup, n - 1):
        dt = dts[i]
        hour = dt.hour
        day = dt.strftime('%Y-%m-%d')
        if not (session[0] <= hour < session[1]):
            continue
        if day_n[day] >= max_trades_day:
            continue
        if i - last_entry_bar < cooldown_bars:
            continue
        av = atr[i]
        if not av:
            continue

        sig = signal_fn(candles, ind, i, dt)
        if sig not in ('buy', 'sell'):
            continue

        entry = candles[i + 1]['o']          # next-bar-open
        tp = round(av * tp_mult, 2)
        sl = round(av * sl_mult, 2)
        tp_p = entry + tp if sig == 'buy' else entry - tp
        sl_dyn = entry - sl if sig == 'buy' else entry + sl

        outcome = 'open'; close_price = entry; exit_stop = False
        for j in range(i + 1, min(i + 1 + max_hold_bars, n)):
            jh, jl, jc = candles[j]['h'], candles[j]['l'], candles[j]['c']
            if be_trail:
                prof = (jc - entry) if sig == 'buy' else (entry - jc)
                if prof >= sl * 0.8:
                    sl_dyn = (entry + 0.2) if sig == 'buy' else (entry - 0.2)
                if prof >= sl * 1.4:
                    trail = jc - sl * 0.7 if sig == 'buy' else jc + sl * 0.7
                    sl_dyn = max(sl_dyn, trail) if sig == 'buy' else min(sl_dyn, trail)
            res = SE2.resolve_intrabar(jh, jl, tp_p, sl_dyn, sig == 'buy')
            if res == 'win':
                outcome = 'win'; close_price = tp_p; break
            if res == 'loss':
                outcome = 'loss'; close_price = sl_dyn; exit_stop = True; break
        if outcome == 'open':
            continue

        pnl = (close_price - entry) if sig == 'buy' else (entry - close_price)
        pnl -= _trade_cost(exit_stop)
        trades.append({'date': day, 'hour': hour, 'dir': sig, 'entry': round(entry, 2),
                       'outcome': 'win' if pnl > 0 else 'loss', 'pnl': round(pnl, 2),
                       'strategy': signal_fn.__name__})
        day_n[day] += 1
        last_entry_bar = i
    return trades


def evaluate(name, tf, signal_fn, **kw):
    trades = run_signal(tf, signal_fn, **kw)
    wf = SE2.walk_forward_report(trades, folds=ARGS.folds, holdout_frac=ARGS.holdout_frac)
    return {
        'name': name, 'tf': tf, 'n_trades': len(trades),
        'full': wf['full'] if wf else SE2.stats(trades),
        'folds': wf['folds'] if wf else [],
        'holdout': wf['holdout'] if wf else SE2.stats([]),
        'holdout_start': wf['holdout_start'] if wf else None,
        'trades': trades,
    }


def pos_folds(ev):
    return sum(1 for s in ev['folds'] if s['pf'] >= 1.0)


def _fmt(s):
    if not s or not s.get('n'):
        return 'n=0'
    return (f"n={s['n']:>4}  WR={s['wr']:>5.1f}%  PF={s['pf']:>6.3f}  "
            f"pnl={s['pnl']:>10.1f}pt  DD={s['dd']:>8.1f}  mesi+={s['months']}")


def print_eval(ev):
    print(f"\n═══ {ev['name']}  [{ev['tf']}]  ({ev['n_trades']} trade) ═══")
    print(f"  full   : {_fmt(ev['full'])}")
    for k, s in enumerate(ev['folds'], 1):
        print(f"  fold {k} : {_fmt(s)}")
    print(f"  HOLDOUT: {_fmt(ev['holdout'])}   (da {ev['holdout_start']})")
    print(f"  fold positivi (PF>=1): {pos_folds(ev)}/{len(ev['folds'])}")


if __name__ == '__main__':
    import us30_strategies as S
    costs = 'OFF' if ARGS.no_costs else f"half-spread={ARGS.spread} slipSL={ARGS.sl_slippage}"
    print(f"US30 harness — cost model: {costs} | folds={ARGS.folds} holdout={ARGS.holdout_frac:.0%}")

    for spec in S.REGISTRY:
        if ARGS.strategy and spec['name'] != ARGS.strategy:
            continue
        tfs = [ARGS.tf] if ARGS.tf else spec['tfs']
        for tf in tfs:
            ev = evaluate(spec['name'], tf, spec['fn'], **spec.get('params', {}))
            print_eval(ev)
