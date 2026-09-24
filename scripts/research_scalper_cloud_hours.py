#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ricerca 2026-09-24 — "XAU Scalper Cloud v3" su M5: in quali ORE funziona?

Riusa il port fedele di scripts/research_scalper_cloud.py (stessi segnali, SL Donchian
± 0.3 ATR, TP 2R, cost model, una posizione alla volta). Tre set di segnali:
  V0_PINE (entrambi), V1_TREND (pullback nuvola), V2_REV (reversal Bollinger).

Anti data-snooping: le ore si scelgono SOLO sul TRAIN (prima dell'holdout) con una regola
fissata prima di guardare: ora con PF >= 1.2 e n >= 30 nel TRAIN. Poi si verifica il
filtro orario risultante sull'HOLDOUT, e sulla stabilità tra le due metà del TRAIN.
Ore = ora BROKER (UTC+3 estate / +2 inverno; Londra apre alle 10, New York alle 16:30).

USO: python -X utf8 scripts/research_scalper_cloud_hours.py
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opt_harness as OH
import research_trials as RT
import research_scalper_cloud as SC

SE2 = OH.SE2
PF_MIN, N_MIN = 1.2, 30


def pf(tr):
    gw = sum(t['pnl'] for t in tr if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in tr if t['pnl'] <= 0)) or 1e-9
    return gw / gl


def main():
    candles, _ = OH._data_for('M5')
    I = SC.indicators(candles)
    I['d1_ema'], I['d1_prev'] = SC.d1_bias(candles)
    num_trials = RT.record_trials(3, asset='XAU', strategy_id='SCALPER_CLOUD',
                                  note='filtro orario scelto sul TRAIN (PF>=1.2, n>=30) per V0/V1/V2 (2026-09-24)')
    print(f"Trial cumulativi: {num_trials}\n")

    for name in ('V0_PINE', 'V1_TREND', 'V2_REV'):
        tr = SC.run(candles, I, **SC.VARIANTS[name])
        train, hold = SE2.split_holdout(tr, 0.2)
        days = sorted(set(t['date'] for t in train)); half = days[len(days) // 2]
        print(f"=================== {name} ===================")
        print(f"TRAIN {train[0]['date']}..{train[-1]['date']}  ·  HOLDOUT da {hold[0]['date']}")
        print(" ora | TRAIN n    PF  | 1a metà PF | 2a metà PF | HOLDOUT n   PF")
        chosen = []
        for h in range(24):
            a = [t for t in train if t['hour'] == h]
            if not a: continue
            a1 = [t for t in a if t['date'] < half]; a2 = [t for t in a if t['date'] >= half]
            b = [t for t in hold if t['hour'] == h]
            ok = pf(a) >= PF_MIN and len(a) >= N_MIN
            if ok: chosen.append(h)
            print(f"  {h:02d} | {len(a):5d} {pf(a):5.2f} |   {pf(a1):5.2f}    |   {pf(a2):5.2f}    | {len(b):5d} {pf(b):5.2f}" + ('   ◀ scelta' if ok else ''))
        print(f"\nOre scelte sul TRAIN: {chosen}")
        if chosen:
            ft = [t for t in train if t['hour'] in chosen]; fh = [t for t in hold if t['hour'] in chosen]
            print(f"  TRAIN  filtrato: {OH.fmt(SE2.stats(ft))}")
            print(f"  HOLDOUT filtrato: {OH.fmt(SE2.stats(fh))}   ← verifica vera")
            print(f"  HOLDOUT senza filtro: {OH.fmt(SE2.stats(hold))}")
            bd = len(set(t['date'] for t in fh)) or 1
            print(f"  trade/giorno attivo nell'holdout filtrato: {len(fh)/bd:.1f}")
        print()


if __name__ == '__main__' and '--verify' not in sys.argv:
    main()


# ── Verifica con il filtro orario applicato DAVVERO all'ingresso (2026-09-24) ─────
# Il filtro a posteriori sopra non cambia l'occupazione della posizione: qui il bot non
# entra fuori orario, quindi è libero per il segnale successivo. Ore = quelle scelte sul
# TRAIN per V2_REV (nessuna nuova scelta, nessun trial aggiuntivo oltre a quello dichiarato).
# python -X utf8 scripts/research_scalper_cloud_hours.py --verify
V2_HOURS = {3, 7, 13, 14, 16}


def verify():
    candles, _ = OH._data_for('M5')
    I = SC.indicators(candles)
    I['d1_ema'], I['d1_prev'] = SC.d1_bias(candles)
    tr = SC.run(candles, I, use_trend=False, hours=V2_HOURS)
    wf = SE2.walk_forward_report(tr, folds=4, holdout_frac=0.2)
    train, hold = SE2.split_holdout(tr, 0.2)
    bd = len(set(t['date'] for t in tr)) or 1
    print(f"V2_REV con ore {sorted(V2_HOURS)} applicate all'ingresso")
    print(f"  full   : {OH.fmt(SE2.stats(tr))}   trade/giorno attivo {len(tr)/bd:.1f}")
    print(f"  TRAIN  : {OH.fmt(SE2.stats(train))}")
    print(f"  HOLDOUT: {OH.fmt(wf['holdout'])}  (da {wf['holdout_start']})")
    print(f"  fold PF: {' / '.join(f'{f['pf']:.2f}' for f in wf['folds'])}")
    print(f"  BUY : {OH.fmt(SE2.stats([t for t in tr if t['dir'] == 'buy']))}")
    print(f"  SELL: {OH.fmt(SE2.stats([t for t in tr if t['dir'] == 'sell']))}")
    for h in sorted(V2_HOURS):
        print(f"    ora {h:02d}: {OH.fmt(SE2.stats([t for t in tr if t['hour'] == h]))}")
    saved = SE2.HALF_SPREAD_USD, SE2.SLIP_ENTRY_USD, SE2.SLIP_SL_USD
    SE2.HALF_SPREAD_USD, SE2.SLIP_ENTRY_USD, SE2.SLIP_SL_USD = [2 * x for x in saved]
    print(f"  costi ×2: {OH.fmt(SE2.stats(SC.run(candles, I, use_trend=False, hours=V2_HOURS)))}")
    SE2.HALF_SPREAD_USD, SE2.SLIP_ENTRY_USD, SE2.SLIP_SL_USD = saved
    dsr = OH.dsr_check({'trades': tr}, RT.total_trials())
    print(f"  DSR ({RT.total_trials()} trial): {'n/d' if dsr is None else ('SIGNIFICATIVO' if dsr.is_significant else 'non significativo')}")
    import numpy as np
    print(f"  rischio medio per trade ${np.mean([t['risk'] for t in tr]):.1f}")


if __name__ == '__main__' and '--verify' in sys.argv:
    verify()
