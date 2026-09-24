#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ricerca 2026-09-24 — combo di portafoglio XAU: roster valido + ASIA_BREAK.

Periodo comune = inizio dati M5 (circa 2025-04-28) → oggi. Nessuna logica duplicata:
  - S16 / S00 V3 / S17 via opt_harness.evaluate (pool condiviso, MAX_OPEN_ORDERS=2 via
    portfolio_backtest.simulate_shared_pool_concurrency)
  - S31 via layout_smart.evaluate_ls_frozen (isolata)
  - ASIA_BREAK(_ALL) via research_session_scalps.run (isolata, M5)
  - S30 (US30) riportata a parte: altro strumento, P&L non sommabile in $ XAU.
P&L = movimento prezzo per unità (stessa convenzione di tutti gli harness): la combo
confronta configurazioni, non stima l'euro sul conto (il sizing live è del RiskGuardian).

USO: python -X utf8 scripts/research_combo.py
"""
import datetime
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opt_harness as OH
import signals as SIG
import portfolio_backtest as PB
import research_session_scalps as RS
import layout_smart as LS

SE2 = OH.SE2


def tag(trades, sid):
    return [dict(t, strategy=sid) for t in trades]


def summary(label, trades, start):
    trades = sorted([t for t in trades if t['date'] >= start], key=lambda t: t['entry_ts'] if 'entry_ts' in t else 0)
    if not trades:
        print(f"{label}: nessun trade"); return
    s = SE2.stats(trades)
    d0 = datetime.date.fromisoformat(start); d1 = datetime.date.fromisoformat(max(t['date'] for t in trades))
    bdays = sum(1 for k in range((d1 - d0).days + 1) if (d0 + datetime.timedelta(k)).weekday() < 5)
    print(f"\n=== {label} ===")
    print(f"  {OH.fmt(s)}")
    print(f"  trade per giorno lavorativo: {len(trades)/bdays:.2f}  ({len(trades)} su {bdays} giorni)")
    by = {}
    for t in trades: by.setdefault(t['strategy'], []).append(t)
    for k, v in sorted(by.items(), key=lambda x: -sum(t['pnl'] for t in x[1])):
        ss = SE2.stats(v)
        print(f"    {k:22s} n={ss['n']:4d} WR={ss['wr']:5.1f}% PF={ss['pf']:6.3f} pnl={ss['pnl']:+8.1f}")


def main():
    m5, _ = OH._data_for('M5')
    start = datetime.datetime.fromtimestamp(m5[0]['t'], datetime.timezone.utc).date().isoformat()
    print(f"Periodo comune da {start}")

    shared = {
        'S16_GOLDEN_SQUEEZE':    {'ev': OH.evaluate('S16_GOLDEN_SQUEEZE', SIG.signal_golden_squeeze, tf='H1')},
        'S00_MFKK':              {'ev': OH.evaluate('S00_MFKK', SIG.signal_mfkk_v3_pull, tf='H1')},
        'S17_CONVERGENCE_SCALP': {'ev': OH.evaluate('S17_CONVERGENCE_SCALP', SIG.signal_convergence_scalp, tf='H4')},
    }
    admitted, blocked = PB.simulate_shared_pool_concurrency(shared)
    s31 = tag(LS.evaluate_ls_frozen(tf='H1')['trades'], 'S31_LAYOUT_SMART')

    P = RS.prepare(m5); RS.LOOKAHEAD = 288
    ab_d1 = tag(RS.run(m5, P, 'ASIA_BREAK', partial=True), 'ASIA_BREAK_D1')
    ab_all = tag(RS.run(m5, P, 'ASIA_BREAK_ALL', partial=True), 'ASIA_BREAK_ALL')

    roster = admitted + s31
    summary("A) roster attuale (S16 + S00 V3 + S17 + S31)", roster, start)
    summary("B) roster + ASIA_BREAK con filtro D1 (parziale)", roster + ab_d1, start)
    summary("C) roster + ASIA_BREAK senza filtro (parziale)", roster + ab_all, start)
    print(f"\n(pool condiviso: {len(blocked)} segnali scartati per MAX_OPEN_ORDERS=2 sull'intero storico)")

    import us30_harness as U30
    from us30_strategies import dow_dip_d1, REGISTRY
    spec = next(s for s in REGISTRY if s['name'] == 'dow_dip_d1')
    ev30 = U30.evaluate('S30_DOW_DIP', 'H4', dow_dip_d1, **spec['params'])
    t30 = [t for t in ev30['trades'] if t['date'] >= start]
    print(f"\nS30_DOW_DIP (US30, a parte): {len(t30)} trade nel periodo, {OH.fmt(SE2.stats(t30))}")


if __name__ == '__main__':
    main()
