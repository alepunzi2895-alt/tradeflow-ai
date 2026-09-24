#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Re-backtest completo del roster live (2026-09-17)
═══════════════════════════════════════════════════════════════════════════════
Richiesta utente: (1) ri-backtestare tutte le strategie, (2) tracciare equity curve
+ performance fino a 24 mesi per ciascuna, (3) validare lo StrategySelector attuale
(regime → strategia) sui 24 mesi, (4) ricalcolare la performance combinata di TUTTE
le strategie sullo stesso conto.

Nessuna logica duplicata (regola CLAUDE.md) — riusa SOLO:
  - opt_harness.evaluate() / strategy-engine-v2.run_one() per il pool condiviso XAU
    (S00/S09/S10/S16/S17/S18, MAX_OPEN_ORDERS=2 come in mt5-bot.py)
  - layout_smart.evaluate_ls_frozen() per S31_LAYOUT_SMART (isolata, H1)
  - us30_harness.evaluate() + us30_strategies.dow_dip_d1 per S30_DOW_DIP (isolata, US30 H4)
  - strategy_selector.detect_regime_extended() per la validazione regime

NB: S32/S33/S34 esclusi — sono "solo score" (nessun ordine, vedi 02_strategies.md),
    non hanno un trade set da backtestare in questo senso. S20_FIB_CONFLUENCE incluso
    (isolata, via run_one esistente).

USO:
    python scripts/portfolio_backtest.py
    python scripts/portfolio_backtest.py --out backtests/results/portfolio_2026-09-17.json
"""
import argparse
import json
import os
import sys
import datetime

# Console Windows (cp1252) va in UnicodeEncodeError su emoji/simboli — stesso fix già
# applicato altrove nel progetto per gli script lanciati come subprocess (vedi
# daily_maintenance.py / 06_known_issues.md 2026-09-01).
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import opt_harness as OH
import signals as SIG
from strategy_selector import STRATEGIES_CONFIG, detect_regime_extended, _REGIME_ALIAS

MAX_OPEN_ORDERS = 2  # scripts/mt5-bot.py

# Stato live al 2026-09-17 dopo il giro di disattivazioni (data/hard_blocks.json +
# S20_ENABLED=False in mt5-bot.py) — usato solo da --active-only, non tocca is_hard_blocked()
# reale (fonte di verità resta data/hard_blocks.json / mt5-bot.py).
from strategy_registry import SNAPSHOT
DISABLED_NOW = {key for key,item in SNAPSHOT['strategies'].items() if item['status'] != 'eligible'}

# Strategia → (tf live, funzione segnale) per il pool condiviso XAU (StrategySelector,
# soggetto a MAX_OPEN_ORDERS). TF = best_tf storico in STRATEGIES_CONFIG.
SHARED_POOL = {
    'S00_MFKK':              ('H1',  SIG.signal_mfkk_v3_pull),   # V3 dal 2026-09-24
    'S09_MFKK_SCALPING':     ('M30', SIG.signal_mfkk_scalping),
    'S10_OB_FVG_SCALP':      ('M30', SIG.signal_ob_fvg_scalp),
    'S16_GOLDEN_SQUEEZE':    ('H1',  SIG.signal_golden_squeeze),
    'S17_CONVERGENCE_SCALP': ('H4',  SIG.signal_convergence_scalp),
    'S18_RANGE_REVERSAL':    ('M30', SIG.signal_range_reversal),
}


def _cfg_by_id(sid):
    return next(c for c in STRATEGIES_CONFIG if c['id'] == sid)


def run_shared_pool(active_only=False):
    """Ri-backtesta i membri del pool condiviso XAU al loro TF live.
    active_only=True salta le strategie disattivate (DISABLED_NOW) invece di backtestarle
    e scartarle dopo — più veloce e riflette lo stato live attuale."""
    out = {}
    for sid, (tf, fn) in SHARED_POOL.items():
        if active_only and sid in DISABLED_NOW:
            continue
        print(f"[shared] {sid} @ {tf} ...", flush=True)
        ev = OH.evaluate(sid, fn, tf=tf)
        out[sid] = {'tf': tf, 'ev': ev}
        print(f"  full   : {OH.fmt(ev['full'])}")
        print(f"  HOLDOUT: {OH.fmt(ev['holdout'])}  (da {ev['holdout_start']})")
    return out


def run_isolated(active_only=False):
    """Ri-backtesta i blocchi isolati (non contano in MAX_OPEN_ORDERS)."""
    out = {}

    # S20_FIB_CONFLUENCE — via run_one esistente (branch dedicato sim_fib_confluence)
    if not (active_only and 'S20_FIB_CONFLUENCE' in DISABLED_NOW):
        print("[isolated] S20_FIB_CONFLUENCE @ M5 ...", flush=True)
        ev20 = OH.evaluate('S20_FIB_CONFLUENCE', SIG.signal_fib_confluence, tf='M5')
        out['S20_FIB_CONFLUENCE'] = {'tf': 'M5', 'ev': ev20}
        print(f"  full   : {OH.fmt(ev20['full'])}")
        print(f"  HOLDOUT: {OH.fmt(ev20['holdout'])}  (da {ev20['holdout_start']})")

    # S31_LAYOUT_SMART — via layout_smart.evaluate_ls_frozen (config produzione)
    print("[isolated] S31_LAYOUT_SMART @ H1 ...", flush=True)
    import layout_smart as LS
    ev31 = LS.evaluate_ls_frozen(tf='H1')
    out['S31_LAYOUT_SMART'] = {'tf': 'H1', 'ev': ev31}
    print(f"  full   : {OH.fmt(ev31['full'])}")
    print(f"  HOLDOUT: {OH.fmt(ev31['holdout'])}  (da {ev31['holdout_start']})")

    # S30_DOW_DIP — via us30_harness.evaluate + us30_strategies.dow_dip_d1 (config REGISTRY)
    print("[isolated] S30_DOW_DIP @ H4 (US30) ...", flush=True)
    import us30_harness as U30
    from us30_strategies import dow_dip_d1, REGISTRY as U30_REGISTRY
    spec = next(s for s in U30_REGISTRY if s['name'] == 'dow_dip_d1')
    ev30 = U30.evaluate('S30_DOW_DIP', 'H4', dow_dip_d1, **spec['params'])
    out['S30_DOW_DIP'] = {'tf': 'H4', 'ev': ev30}
    print(f"  full   : {OH.fmt(ev30['full'])}")
    print(f"  HOLDOUT: {OH.fmt(ev30['holdout'])}  (da {ev30['holdout_start']})")

    return out


def evaluate_one(strategy_id):
    """Ri-backtesta UNA sola strategia (qualunque, condivisa o isolata) — usato dal worker
    on-demand (scripts/backtest_worker.py) per il bottone 'Lancia backtest' della dashboard.
    Ritorna lo stesso shape di run_shared_pool()/run_isolated() per quella singola chiave,
    più l'equity curve pronta per il frontend. Nessuna logica duplicata: stessa evaluate()
    per-strategia usata dal run completo."""
    if strategy_id in SHARED_POOL:
        tf, fn = SHARED_POOL[strategy_id]
        ev = OH.evaluate(strategy_id, fn, tf=tf)
    elif strategy_id == 'S20_FIB_CONFLUENCE':
        tf = 'M5'
        ev = OH.evaluate(strategy_id, SIG.signal_fib_confluence, tf=tf)
    elif strategy_id == 'S31_LAYOUT_SMART':
        import layout_smart as LS
        tf = 'H1'
        ev = LS.evaluate_ls_frozen(tf=tf)
    elif strategy_id == 'S30_DOW_DIP':
        import us30_harness as U30
        from us30_strategies import dow_dip_d1, REGISTRY as U30_REGISTRY
        spec = next(s for s in U30_REGISTRY if s['name'] == 'dow_dip_d1')
        tf = 'H4'
        ev = U30.evaluate(strategy_id, tf, dow_dip_d1, **spec['params'])
    else:
        raise ValueError(f"strategy_id sconosciuto: {strategy_id}")

    return {
        'strategy_id': strategy_id, 'tf': tf,
        'full': ev['full'], 'holdout': ev['holdout'], 'holdout_start': ev['holdout_start'],
        'n_trades': len(ev['trades']),
        'equity_curve': OH.SE2.equity_curve(ev['trades']),
    }


# ── COMBINED PORTFOLIO SIMULATION ────────────────────────────────────────────
def simulate_shared_pool_concurrency(shared):
    """Simula la reale contesa per MAX_OPEN_ORDERS tra i trade del pool condiviso:
    ordina per entry_ts, ammette solo se < MAX_OPEN_ORDERS posizioni aperte in quel
    momento (le posizioni si liberano al loro exit_ts) — i segnali in eccesso vengono
    scartati esattamente come farebbe mt5-bot.py::quality_gate() dal vivo."""
    all_trades = []
    for sid, data in shared.items():
        for t in data['ev']['trades']:
            if 'entry_ts' not in t:
                continue  # S20 passa da qui solo se richiamato per errore — non è il caso
            tt = dict(t)
            tt['strategy'] = sid
            all_trades.append(tt)
    all_trades.sort(key=lambda t: t['entry_ts'])

    open_until = []  # lista di exit_ts delle posizioni correntemente aperte
    admitted, blocked = [], []
    for t in all_trades:
        open_until = [e for e in open_until if e > t['entry_ts']]
        if len(open_until) < MAX_OPEN_ORDERS:
            open_until.append(t['exit_ts'])
            admitted.append(t)
        else:
            blocked.append(t)
    return admitted, blocked


def daily_pnl(trades, date_key=lambda t: t['date']):
    by_day = {}
    for t in trades:
        by_day[date_key(t)] = by_day.get(date_key(t), 0.0) + t['pnl']
    return by_day


def combined_stats(all_admitted_trades):
    """Stats aggregate stile backtest_combined.py, ma su dati reali del roster attuale."""
    if not all_admitted_trades:
        return {}
    trades = sorted(all_admitted_trades, key=lambda t: t['date'])
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    gw = sum(t['pnl'] for t in wins)
    gl = abs(sum(t['pnl'] for t in losses)) or 1e-9
    cum = 0.0; peak = 0.0; dd = 0.0; curve = []
    for t in trades:
        cum += t['pnl']
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        curve.append({'date': t['date'], 'cum_pnl': round(cum, 2)})
    last_day = trades[-1]['date']

    def _cut(months):
        cutoff = (datetime.date.fromisoformat(last_day) - datetime.timedelta(days=30 * months)).isoformat()
        sub = [t for t in trades if t['date'] >= cutoff]
        return round(sum(t['pnl'] for t in sub), 2), len(sub)

    by_strat = {}
    for t in trades:
        by_strat.setdefault(t['strategy'], []).append(t)

    pnl_1m, n_1m = _cut(1); pnl_6m, n_6m = _cut(6); pnl_12m, n_12m = _cut(12); pnl_24m, n_24m = _cut(24)
    return {
        'n_trades': len(trades), 'wr': round(100 * len(wins) / len(trades), 1),
        'pf': round(gw / gl, 3), 'total_pnl': round(cum, 2), 'max_dd': round(dd, 2),
        'pnl_1m': pnl_1m, 'n_1m': n_1m, 'pnl_6m': pnl_6m, 'n_6m': n_6m,
        'pnl_12m': pnl_12m, 'n_12m': n_12m, 'pnl_24m': pnl_24m, 'n_24m': n_24m,
        'by_strategy': {k: {
            'n': len(v), 'pnl': round(sum(t['pnl'] for t in v), 2),
            'wr': round(100 * sum(1 for t in v if t['pnl'] > 0) / len(v), 1),
        } for k, v in by_strat.items()},
        'equity_curve': curve,
    }


# ── REGIME VALIDATION ────────────────────────────────────────────────────────
def validate_regime_matching(shared):
    """Per ogni strategia del pool condiviso: regime al momento dell'ingresso di ogni
    trade reale (via detect_regime_extended sullo stesso ind/tf del backtest) → PF/WR
    per regime canonico, confrontato con optimal_regimes già codificato in STRATEGIES_CONFIG."""
    report = {}
    for sid, data in shared.items():
        tf = data['tf']
        candles, ind = OH._data_for(tf)
        cfg = _cfg_by_id(sid)
        by_regime = {}
        for t in data['ev']['trades']:
            idx = t.get('entry_idx')
            if idx is None:
                continue
            reg = detect_regime_extended(ind, idx)
            canon = _REGIME_ALIAS.get(reg['type'], 'WEAK')
            by_regime.setdefault(canon, []).append(t['pnl'])
        regime_stats = {}
        for reg, pnls in by_regime.items():
            wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
            gw = sum(wins); gl = abs(sum(losses)) or 1e-9
            regime_stats[reg] = {'n': len(pnls), 'pf': round(gw / gl, 3),
                                  'wr': round(100 * len(wins) / len(pnls), 1) if pnls else 0,
                                  'pnl': round(sum(pnls), 2)}
        report[sid] = {'optimal_regimes_coded': cfg['optimal_regimes'], 'observed': regime_stats}
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--active-only', action='store_true',
                     help='Salta le strategie disattivate (DISABLED_NOW) — riflette il roster live attuale')
    ap.add_argument('--out', default=None)
    ap.add_argument('--push', action='store_true',
                     help='POSTa il report completo (full + solo attive derivate dallo stesso run) su Turso via '
                          '/api/db backtest_report_push, per il pannello Report Backtest nel tab Strategie. '
                          'Incompatibile con --active-only (richiede il run completo per derivare entrambe le viste).')
    args = ap.parse_args()
    if args.push and args.active_only:
        print("--push richiede il run completo: rimuovi --active-only (la vista attiva viene derivata comunque).")
        sys.exit(1)
    out_default = 'portfolio_active_2026-09-17.json' if args.active_only else 'portfolio_2026-09-17.json'
    out_path = args.out or os.path.join(HERE, '..', 'backtests', 'results', out_default)

    print("=" * 70)
    print("RE-BACKTEST ROSTER LIVE — 2026-09-17" + (" (SOLO STRATEGIE ATTIVE)" if args.active_only else ""))
    print("=" * 70)

    shared = run_shared_pool(active_only=args.active_only)
    isolated = run_isolated(active_only=args.active_only)

    print("\n" + "=" * 70)
    print("SIMULAZIONE CONCORRENZA POOL CONDIVISO (MAX_OPEN_ORDERS=2)")
    print("=" * 70)
    admitted, blocked = simulate_shared_pool_concurrency(shared)
    print(f"  Trade generati dal pool condiviso : {sum(len(d['ev']['trades']) for d in shared.values())}")
    print(f"  Ammessi (slot disponibile)        : {len(admitted)}")
    print(f"  Scartati (MAX_OPEN_ORDERS pieno)  : {len(blocked)}")

    all_combined = list(admitted)
    for sid, data in isolated.items():
        for t in data['ev']['trades']:
            tt = dict(t); tt['strategy'] = sid
            all_combined.append(tt)

    print("\n" + "=" * 70)
    print("PERFORMANCE COMBINATA — TUTTE LE STRATEGIE, STESSO CONTO")
    print("=" * 70)
    cs = combined_stats(all_combined)
    if cs:
        print(f"  Trade totali : {cs['n_trades']}  WR {cs['wr']}%  PF {cs['pf']}")
        print(f"  P&L totale   : {cs['total_pnl']:+.1f}   Max DD: {cs['max_dd']:.1f}")
        print(f"  1m : {cs['pnl_1m']:+.1f} ({cs['n_1m']} tr)   6m : {cs['pnl_6m']:+.1f} ({cs['n_6m']} tr)")
        print(f"  12m: {cs['pnl_12m']:+.1f} ({cs['n_12m']} tr)  24m: {cs['pnl_24m']:+.1f} ({cs['n_24m']} tr)")
        print("\n  Per strategia:")
        for k, v in sorted(cs['by_strategy'].items(), key=lambda x: -x[1]['pnl']):
            print(f"    {k:24s} n={v['n']:4d}  WR={v['wr']:5.1f}%  P&L={v['pnl']:+9.1f}")

    print("\n" + "=" * 70)
    print("VALIDAZIONE REGIME (StrategySelector) SUI TRADE REALI")
    print("=" * 70)
    regime_report = validate_regime_matching(shared)
    for sid, rep in regime_report.items():
        print(f"\n  {sid}  (optimal_regimes codificati: {rep['optimal_regimes_coded']})")
        for reg, s in sorted(rep['observed'].items(), key=lambda x: -x[1]['pnl']):
            flag = '✓' if reg in rep['optimal_regimes_coded'] else '⚠ NON in optimal_regimes'
            print(f"    {reg:10s} n={s['n']:4d}  PF={s['pf']:6.3f}  WR={s['wr']:5.1f}%  "
                  f"pnl={s['pnl']:+9.1f}  {flag}")

    # ── Individual equity curves (24 mesi, tutte le TF hanno storia sufficiente) ──
    equity_curves = {}
    for sid, data in {**shared, **isolated}.items():
        ec = OH.SE2.equity_curve(data['ev']['trades'])
        equity_curves[sid] = ec

    output = {
        'generated_at': datetime.datetime.utcnow().isoformat(),
        'max_open_orders': MAX_OPEN_ORDERS,
        'shared_pool': {sid: {'tf': d['tf'], 'full': d['ev']['full'], 'holdout': d['ev']['holdout'],
                               'holdout_start': d['ev']['holdout_start'], 'n_trades': len(d['ev']['trades'])}
                        for sid, d in shared.items()},
        'isolated': {sid: {'tf': d['tf'], 'full': d['ev']['full'], 'holdout': d['ev']['holdout'],
                            'holdout_start': d['ev']['holdout_start'], 'n_trades': len(d['ev']['trades'])}
                     for sid, d in isolated.items()},
        'concurrency': {'n_admitted': len(admitted), 'n_blocked': len(blocked)},
        'combined_stats': cs,
        'regime_validation': regime_report,
        'equity_curves': equity_curves,
    }

    # ── Vista "solo attive" derivata dallo STESSO run (no re-backtest) ──────────
    # Solo quando si è girato il roster completo: filtra i trade delle strategie in
    # DISABLED_NOW dai medesimi risultati già calcolati sopra, invece di rilanciare
    # opt_harness.evaluate() una seconda volta (--active-only fa quello, per un check
    # rapido isolato; qui serve avere ENTRAMBE le viste da un solo run per il pannello
    # Report Backtest nel tab Strategie, vedi public/modules/backtest-report.js).
    if not args.active_only:
        shared_active = {k: v for k, v in shared.items() if k not in DISABLED_NOW}
        isolated_active = {k: v for k, v in isolated.items() if k not in DISABLED_NOW}
        admitted_a, blocked_a = simulate_shared_pool_concurrency(shared_active)
        all_combined_a = list(admitted_a)
        for sid, data in isolated_active.items():
            for t in data['ev']['trades']:
                tt = dict(t); tt['strategy'] = sid
                all_combined_a.append(tt)
        cs_active = combined_stats(all_combined_a)
        output['disabled'] = sorted(DISABLED_NOW)
        output['concurrency_active'] = {'n_admitted': len(admitted_a), 'n_blocked': len(blocked_a)}
        output['active_combined_stats'] = cs_active
        if cs_active:
            print("\n" + "=" * 70)
            print("PERFORMANCE SOLO ATTIVE (derivata, stesso run)")
            print("=" * 70)
            print(f"  Trade totali : {cs_active['n_trades']}  WR {cs_active['wr']}%  PF {cs_active['pf']}")
            print(f"  P&L totale   : {cs_active['total_pnl']:+.1f}   Max DD: {cs_active['max_dd']:.1f}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSalvato: {out_path}")

    if args.push:
        from vercel_push import push
        try:
            push('backtest_report_push', {'report': output}, timeout=25)
            print("Pushato su Turso (backtest_report_push).")
        except Exception as e:
            print(f"Push a Turso fallito (non bloccante, il file locale è comunque salvato): {e}")


if __name__ == '__main__':
    main()
