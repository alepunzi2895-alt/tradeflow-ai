#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ricerca 2026-09-24 — S00_MFKK come fallback H1 quando il regime è TREND_DOWN.

Contesto: in TREND_DOWN il selector sceglie solo S16@H1; S16 vende solo come
contro-trend dentro un H4 rialzista, quindi con H1+H4 ribassisti il bot resta
fermo (bot senza trade dal 16/09). Domanda: aggiungere S00 come riserva in
TREND_DOWN (solo quando S16 non ha una posizione aperta) migliora il sistema?

Nessuna logica duplicata: opt_harness.evaluate() (run_one con cost model,
walk-forward, holdout) + strategy_selector.detect_regime_extended().

Varianti (tutte dichiarate in research_trials):
  A  = solo S16                         (baseline, stato live)
  B  = S16 + S00 in TREND_DOWN          (proposta)
  C  = S16 + S00 in TREND_DOWN+TREND_UP (sensibilità)

USO: python -X utf8 scripts/research_s00_trend_fallback.py
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opt_harness as OH
import signals as SIG
import research_trials as RT
from strategy_selector import detect_regime_extended

TF = 'H1'
N_VARIANTS = 3


def regime_at(ind, idx):
    return detect_regime_extended(ind, idx)['type']


def overlaps(t, busy):
    return any(b['entry_ts'] <= t['entry_ts'] < b['exit_ts'] for b in busy)


def summarize(label, trades, holdout_start):
    trades = sorted(trades, key=lambda t: t['entry_ts'])
    full = OH.SE2.stats(trades)
    hold = OH.SE2.stats([t for t in trades if t['date'] >= holdout_start])
    print(f"{label}\n  full   : {OH.fmt(full)}\n  HOLDOUT: {OH.fmt(hold)}")
    return full, hold


def main():
    ev16 = OH.evaluate('S16_GOLDEN_SQUEEZE', SIG.signal_golden_squeeze, tf=TF)
    ev00 = OH.evaluate('S00_MFKK', SIG.signal_mfkk_score, tf=TF)
    _, ind = OH._data_for(TF)
    hs = ev16['holdout_start']
    print(f"Holdout da {hs}\n")

    s16 = ev16['trades']
    for t in ev00['trades']:
        t['_reg'] = regime_at(ind, t['entry_idx'])

    def fallback(regimes):
        return [t for t in ev00['trades'] if t['_reg'] in regimes and not overlaps(t, s16)]

    fb_down = fallback({'TREND_DOWN'})
    fb_both = fallback({'TREND_DOWN', 'TREND_UP'})

    summarize("A) solo S16 (live)", s16, hs)
    summarize("B) S16 + S00 fallback TREND_DOWN", s16 + fb_down, hs)
    summarize("C) S16 + S00 fallback TREND_DOWN+UP", s16 + fb_both, hs)
    print()
    summarize("   solo trade S00 aggiunti in B", fb_down, hs)
    for d in ('buy', 'sell'):
        summarize(f"     di cui {d.upper()}", [t for t in fb_down if t.get('dir', t.get('direction')) == d], hs)
    summarize("   solo trade S00 aggiunti in C", fb_both, hs)

    # Walk-forward sulla variante proposta (fold sulla stessa suddivisione del motore)
    wf = OH.SE2.walk_forward_report(sorted(s16 + fb_down, key=lambda t: t['entry_ts']), folds=4, holdout_frac=0.2)
    if wf:
        print("\nB) fold:", ' | '.join(f"PF {f['pf']:.2f} n={f['n']}" for f in wf['folds']))

    num_trials = RT.record_trials(N_VARIANTS, asset='XAU', strategy_id='S00_MFKK',
                                  note='fallback S00 in TREND_DOWN/UP accanto a S16 H1 (2026-09-24)')
    dsr = OH.dsr_check({'trades': fb_down}, num_trials)
    if dsr is None:
        print(f"\nDSR (trade S00 aggiunti, {num_trials} trial cumulativi): n/d, holdout troppo corto")
    else:
        print(f"\nDSR (trade S00 aggiunti, {num_trials} trial cumulativi): sr={dsr.observed_sr:.3f} "
              f"p={dsr.dsr_pvalue:.3f} -> {'SIGNIFICATIVO' if dsr.is_significant else 'non significativo'}")


if __name__ == '__main__':
    main()
